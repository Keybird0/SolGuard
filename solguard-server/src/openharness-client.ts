// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { spawn, type ChildProcess } from 'node:child_process';
import { config } from './config';
import { logger } from './logger';
import type { AgentEvent } from './types';

export interface AgentRunOptions {
  prompt: string;
  taskId: string;
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  timeoutMs?: number;
  onEvent?: (event: AgentEvent) => void;
  onStderr?: (chunk: string) => void;
  spawnFn?: typeof spawn;
  cliPath?: string;
  outputFormat?: 'json-stream' | 'json';
}

export interface AgentResult {
  exitCode: number | null;
  stdout: string;
  stderr: string;
  events: AgentEvent[];
  finalResult?: unknown;
  timedOut: boolean;
}

const EVENT_TYPE_MAP: Record<string, AgentEvent['type']> = {
  tool_call_start: 'tool_call_start',
  tool_use_start: 'tool_call_start',
  tool_call_end: 'tool_call_end',
  tool_use_end: 'tool_call_end',
  tool_result: 'tool_call_end',
  thought: 'thought',
  thinking: 'thought',
  final_result: 'final_result',
  final: 'final_result',
  result: 'final_result',
  error: 'error',
};

function parseLine(raw: string): AgentEvent | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  try {
    const obj = JSON.parse(trimmed) as Record<string, unknown>;
    const rawType = (obj.type ?? obj.event ?? '') as string;
    const mapped = EVENT_TYPE_MAP[rawType] ?? 'unknown';
    const tool =
      (obj.tool as string | undefined) ??
      (obj.tool_name as string | undefined) ??
      (obj.name as string | undefined);
    return { type: mapped, tool, data: obj.data ?? obj, raw: trimmed };
  } catch {
    return { type: 'unknown', raw: trimmed };
  }
}

function splitLines(buffer: string): { lines: string[]; rest: string } {
  const parts = buffer.split(/\r?\n/);
  const rest = parts.pop() ?? '';
  return { lines: parts, rest };
}

export async function runAgent(opts: AgentRunOptions): Promise<AgentResult> {
  const spawnFn = opts.spawnFn ?? spawn;
  const cli = opts.cliPath ?? config.ohCliPath;
  const format = opts.outputFormat ?? config.ohOutputFormat;
  const timeoutMs = opts.timeoutMs ?? config.agentTimeoutMs;

  const args = ['-p', opts.prompt, '--output-format', format];

  logger.debug(
    { taskId: opts.taskId, cli, format, timeoutMs },
    'spawning openharness agent',
  );

  return new Promise<AgentResult>((resolve) => {
    let child: ChildProcess;
    try {
      child = spawnFn(cli, args, {
        cwd: opts.cwd,
        env: { ...process.env, ...opts.env },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      logger.error({ err: msg, taskId: opts.taskId }, 'spawn threw');
      resolve({
        exitCode: -1,
        stdout: '',
        stderr: msg,
        events: [{ type: 'error', raw: msg }],
        timedOut: false,
      });
      return;
    }

    const events: AgentEvent[] = [];
    let stdoutBuf = '';
    let stderrBuf = '';
    let pendingLine = '';
    let finalResult: unknown;
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      logger.warn({ taskId: opts.taskId, timeoutMs }, 'agent timed out, killing');
      child.kill('SIGTERM');
      setTimeout(() => {
        if (!child.killed) child.kill('SIGKILL');
      }, 2000).unref?.();
    }, timeoutMs);
    timer.unref?.();

    child.stdout?.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8');
      stdoutBuf += text;
      if (format === 'json-stream') {
        const { lines, rest } = splitLines(pendingLine + text);
        pendingLine = rest;
        for (const line of lines) {
          const evt = parseLine(line);
          if (!evt) continue;
          events.push(evt);
          if (evt.type === 'final_result') finalResult = evt.data;
          try {
            opts.onEvent?.(evt);
          } catch (err) {
            logger.error({ err }, 'onEvent threw');
          }
        }
      }
    });

    child.stderr?.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8');
      stderrBuf += text;
      try {
        opts.onStderr?.(text);
      } catch (err) {
        logger.error({ err }, 'onStderr threw');
      }
    });

    child.on('error', (err) => {
      logger.error({ err: err.message, taskId: opts.taskId }, 'agent process error');
      events.push({ type: 'error', raw: err.message });
    });

    child.on('close', (code) => {
      clearTimeout(timer);
      if (format === 'json' && stdoutBuf.trim()) {
        const match = stdoutBuf.match(/\{[\s\S]*\}$/);
        if (match) {
          try {
            finalResult = JSON.parse(match[0]);
            events.push({ type: 'final_result', data: finalResult, raw: match[0] });
            opts.onEvent?.({ type: 'final_result', data: finalResult, raw: match[0] });
          } catch (err) {
            logger.warn({ err }, 'failed to parse agent stdout as JSON');
          }
        }
      }
      resolve({
        exitCode: code,
        stdout: stdoutBuf,
        stderr: stderrBuf,
        events,
        finalResult,
        timedOut,
      });
    });
  });
}

export async function checkCliAvailable(cliPath: string = config.ohCliPath): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    try {
      const child = spawn(cliPath, ['--version'], { stdio: 'ignore' });
      child.on('error', () => resolve(false));
      child.on('close', (code) => resolve(code === 0));
      setTimeout(() => {
        child.kill();
        resolve(false);
      }, 3000).unref?.();
    } catch {
      resolve(false);
    }
  });
}
