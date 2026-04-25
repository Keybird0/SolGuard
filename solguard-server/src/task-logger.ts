// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
/**
 * Per-task append-only log file.
 *
 * Every lifecycle event that carries a `taskId` is mirrored to
 * `${config.taskLogDir}/${taskId}.log`, with the exact same JSON-line
 * structure that `pino` emits to stdout. Operators can then
 *
 *   tail -f data/logs/<taskId>.log
 *
 * to get the full story of a single audit (submit → pay → normalize →
 * runner → finish) without having to grep the aggregated server log.
 *
 * The file path is exposed at `/api/admin/logs/:taskId` (plain-text
 * tail) behind `ADMIN_TOKEN`, so it is still accessible even after the
 * in-memory / sqlite task row has been purged.
 *
 * Safe properties:
 *  - `taskId` is regex-validated as `[A-Za-z0-9._-]+` so attackers
 *    cannot traverse outside `taskLogDir`.
 *  - File handles are opened lazily and cached in-process; writes are
 *    synchronous `fs.appendFileSync` to keep ordering deterministic and
 *    survive crashes (fsync on exit — Node closes fds on process exit).
 *  - A soft size cap (`TASK_LOG_MAX_BYTES`, default 2 MB) rotates the
 *    file by truncating and prepending a marker, so a runaway task
 *    can't exhaust disk.
 */
import { appendFileSync, mkdirSync, readFileSync, statSync, existsSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { config } from './config';
import { logger } from './logger';

const TASK_ID_RE = /^[A-Za-z0-9._-]{1,64}$/;

let ensuredDir = false;

function ensureLogDir(): string {
  const dir = path.resolve(process.cwd(), config.taskLogDir);
  // Always mkdir — cheap idempotent syscall, and it keeps working if an
  // external process (e.g. test tearDown, log rotator, operator cleanup)
  // deleted the directory after our initial `mkdirSync`. The old cache
  // flag caused silent `ENOENT` on write and hid real failures.
  mkdirSync(dir, { recursive: true });
  ensuredDir = true;
  return dir;
}

/**
 * Turns an arbitrary taskId into an absolute path under `taskLogDir`,
 * or null if the id is invalid. Exposed so tests can assert routing.
 */
export function taskLogPath(taskId: string): string | null {
  if (!TASK_ID_RE.test(taskId)) return null;
  return path.join(ensureLogDir(), `${taskId}.log`);
}

function maybeRotate(filePath: string): void {
  if (!existsSync(filePath)) return;
  try {
    const st = statSync(filePath);
    if (st.size > config.taskLogMaxBytes) {
      // Keep last ~40% of content + rotation marker so operators still
      // see the most recent frames even after trimming.
      const keep = Math.max(256, Math.floor(config.taskLogMaxBytes * 0.4));
      const tail = readFileSync(filePath, 'utf8').slice(-keep);
      writeFileSync(
        filePath,
        JSON.stringify({
          level: 'warn',
          time: Date.now(),
          msg: 'task log rotated — previous lines truncated',
          rotatedAt: new Date().toISOString(),
        }) + '\n' + tail,
      );
    }
  } catch (err) {
    logger.warn({ err, filePath }, 'task log rotation failed');
  }
}

/**
 * Append one JSON frame to the task log. Safe to call with arbitrary
 * untrusted `taskId` — invalid ids are silently dropped and surfaced
 * via pino at debug level.
 */
export function appendTaskLog(
  taskId: string,
  record: Record<string, unknown>,
): void {
  const filePath = taskLogPath(taskId);
  if (!filePath) {
    logger.debug({ taskId }, 'appendTaskLog: invalid taskId');
    return;
  }
  maybeRotate(filePath);
  const frame = {
    level: 'info',
    time: Date.now(),
    taskId,
    ...record,
  };
  try {
    appendFileSync(filePath, JSON.stringify(frame) + '\n');
  } catch (err) {
    // Never throw — logging must not break a request.
    logger.warn({ err, taskId }, 'appendTaskLog failed');
  }
}

/**
 * Returns up to `maxBytes` of the tail of a task log, or null if the
 * taskId is invalid / the file does not exist.
 */
export function readTaskLogTail(
  taskId: string,
  maxBytes: number = 256_000,
): string | null {
  const filePath = taskLogPath(taskId);
  if (!filePath) return null;
  if (!existsSync(filePath)) return null;
  try {
    const st = statSync(filePath);
    if (st.size <= maxBytes) {
      return readFileSync(filePath, 'utf8');
    }
    return readFileSync(filePath, 'utf8').slice(-maxBytes);
  } catch (err) {
    logger.warn({ err, taskId }, 'readTaskLogTail failed');
    return null;
  }
}

/**
 * Thin wrapper that emits both to the global pino logger and the
 * per-task file, so a single call propagates the req_id / taskId and
 * leaves a grep-friendly trail everywhere.
 */
export function logTaskEvent(
  level: 'info' | 'warn' | 'error' | 'debug',
  taskId: string,
  msg: string,
  extra: Record<string, unknown> = {},
): void {
  const payload = { ...extra, taskId };
  const loggerRef = logger as unknown as Record<
    string,
    ((p: unknown, m: string) => void) | undefined
  >;
  const emit = loggerRef[level];
  if (typeof emit === 'function') {
    // Bind so pino keeps its internal `this` even when we look the method
    // up dynamically (Node ≥ 25 is stricter about detached method refs).
    emit.call(logger, payload, msg);
  }
  appendTaskLog(taskId, { level, msg, ...extra });
}
