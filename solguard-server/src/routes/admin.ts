// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
/**
 * /api/admin/* — operator-only endpoints. Gated by the `ADMIN_TOKEN`
 * env var (sent as `X-Admin-Token`). When the token is unset, every
 * endpoint responds 503 so we fail closed instead of leaking logs by
 * default.
 */
import { Router, type Request } from 'express';
import { timingSafeEqual } from 'node:crypto';
import { config } from '../config';
import { readTaskLogTail, taskLogPath } from '../task-logger';

function verifyAdmin(req: Request): { ok: boolean; reason?: string } {
  if (!config.adminToken) {
    return { ok: false, reason: 'ADMIN_TOKEN not configured' };
  }
  const provided = req.header('x-admin-token') ?? '';
  if (!provided) return { ok: false, reason: 'Missing X-Admin-Token' };
  const a = Buffer.from(provided);
  const b = Buffer.from(config.adminToken);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return { ok: false, reason: 'Invalid admin token' };
  }
  return { ok: true };
}

const router = Router();

/**
 * GET /api/admin/logs/:taskId
 *
 * Returns the tail of the task log as `text/plain`. Accepts an
 * optional `?bytes=NNN` query param (capped at 2 MB) for how much of
 * the tail to return.
 */
router.get('/admin/logs/:taskId', (req, res) => {
  const auth = verifyAdmin(req);
  if (!auth.ok) {
    const status = config.adminToken ? 401 : 503;
    res.status(status).json({ code: 'UNAUTHORIZED', message: auth.reason });
    return;
  }

  const taskId = req.params.taskId ?? '';
  const filePath = taskLogPath(taskId);
  if (!filePath) {
    res.status(400).json({ code: 'BAD_TASK_ID', message: 'Invalid taskId format' });
    return;
  }

  const rawBytes = req.query.bytes;
  let bytes = 256_000;
  if (typeof rawBytes === 'string' && rawBytes) {
    const parsed = Number.parseInt(rawBytes, 10);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      res.status(400).json({ code: 'BAD_BYTES', message: 'bytes must be a positive integer' });
      return;
    }
    bytes = Math.min(parsed, 2_000_000);
  }

  const tail = readTaskLogTail(taskId, bytes);
  if (tail === null) {
    res.status(404).json({ code: 'NOT_FOUND', message: 'No log for this taskId' });
    return;
  }

  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.status(200).send(tail);
});

export default router;
