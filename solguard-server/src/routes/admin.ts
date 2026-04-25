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
import { z } from 'zod';
import { config } from '../config';
import { logger } from '../logger';
import { getConnection, verifyPayment } from '../payment';
import { getBatchStore } from '../storage/batch-store';
import { getTaskStore } from '../storage/task-store';
import { notifyPaymentConfirmed } from '../notify/lark';
import { normalizeAndEnqueue } from './audit';
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

/**
 * POST /api/admin/batch/:batchId/force-verify-payment
 * Body: { signature: string }
 *
 * Recovery endpoint for batches that were marked `failed` due to
 * payment-poller issues (public devnet RPC 429s, expiry race, etc.)
 * even though the on-chain transfer is valid. The operator provides
 * the known good signature; we re-run `validateTransfer` against the
 * chain and, on success, revive the batch:
 *   batch.status → paid
 *   every task  → paid, progress="Payment confirmed (force-verify)..."
 *   normalizeAndEnqueue is kicked off so the audit pipeline resumes.
 *
 * Idempotent: if the batch is already paid with the same signature,
 * we return 200 OK without re-enqueuing.
 */
const forceVerifyBody = z.object({ signature: z.string().min(40).max(120) });

router.post('/admin/batch/:batchId/force-verify-payment', async (req, res, next) => {
  try {
    const auth = verifyAdmin(req);
    if (!auth.ok) {
      const status = config.adminToken ? 401 : 503;
      res.status(status).json({ code: 'UNAUTHORIZED', message: auth.reason });
      return;
    }

    const batchId = req.params.batchId ?? '';
    const { signature } = forceVerifyBody.parse(req.body);

    const batchStore = getBatchStore();
    const taskStore = getTaskStore();
    const batch = await batchStore.get(batchId);
    if (!batch) {
      res.status(404).json({ code: 'NOT_FOUND', message: 'Batch not found' });
      return;
    }

    if (!batch.paymentReference || !batch.paymentRecipient || !batch.totalAmountSol) {
      res.status(409).json({
        code: 'PAYMENT_NOT_READY',
        message: 'Batch has no payment request to verify',
      });
      return;
    }

    if (batch.status === 'paid' && batch.paymentSignature === signature) {
      res.status(200).json({
        ok: true,
        status: 'paid',
        signature,
        note: 'already paid — no-op',
      });
      return;
    }

    const verdict = await verifyPayment({
      connection: getConnection(),
      signature,
      reference: batch.paymentReference,
      recipient: batch.paymentRecipient,
      amountSol: batch.totalAmountSol,
    });

    if (!verdict.ok) {
      res.status(400).json({
        ok: false,
        code: 'VALIDATION_FAILED',
        error: verdict.error,
      });
      return;
    }

    const now = new Date().toISOString();
    await batchStore.update(batchId, {
      status: 'paid',
      paymentSignature: signature,
      paymentConfirmedAt: now,
    });

    const enqueued: string[] = [];
    for (const taskId of batch.taskIds) {
      try {
        const updated = await taskStore.update(taskId, {
          status: 'paid',
          paymentSignature: signature,
          error: undefined,
          progress: 'Payment confirmed (force-verify), preparing audit...',
        });
        void notifyPaymentConfirmed(updated).catch((err) =>
          logger.warn({ err, taskId, batchId }, 'lark paid notify failed (force-verify)'),
        );
        void normalizeAndEnqueue(taskId).catch((err) => {
          logger.error({ err, taskId, batchId }, 'normalizeAndEnqueue (force-verify) failed');
        });
        enqueued.push(taskId);
      } catch (err) {
        logger.error({ err, taskId, batchId }, 'force-verify: task flip failed');
      }
    }

    logger.warn(
      { batchId, signature, tasks: enqueued.length, previousStatus: batch.status },
      'batch force-verified via admin endpoint',
    );

    res.status(200).json({
      ok: true,
      status: 'paid',
      signature,
      batchId,
      previousStatus: batch.status,
      tasksEnqueued: enqueued,
    });
  } catch (err) {
    next(err);
  }
});

export default router;
