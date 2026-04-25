// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';
import { Router } from 'express';
import { config, isPaymentConfigured } from '../config';
import { logger } from '../logger';
import {
  createPaymentRequest,
  getConnection,
  verifyPayment as realVerifyPayment,
} from '../payment';
import { getTaskStore } from '../storage/task-store';
import { getBatchStore } from '../storage/batch-store';
import type {
  AuditBatch,
  AuditTask,
  Finding,
  Statistics,
  TaskStatus,
} from '../types';
import {
  agentCompleteSchema,
  createAuditSchema,
  createBatchSchema,
  paymentPushSchema,
  targetToInputs,
} from '../validators/audit';
import { getAuditEngine } from '../audit-engine';
import { normalizeAll as realNormalizeAll, getWorkdirFor } from '../input-normalizer';
import { logTaskEvent } from '../task-logger';
import {
  notifyPaymentConfirmed,
  notifyScanRequested,
} from '../notify/lark';

type NormalizeFn = typeof realNormalizeAll;
let normalizeOverride: NormalizeFn | null = null;

/**
 * Overrides the input normalizer — used in tests to avoid spawning
 * real `git clone` / network calls. Pass `null` to reset.
 */
export function setNormalizerForTesting(fn: NormalizeFn | null): void {
  normalizeOverride = fn;
}

async function runNormalize(
  inputs: AuditTask['inputs'],
  workdir: string,
): Promise<Awaited<ReturnType<NormalizeFn>>> {
  const fn = normalizeOverride ?? realNormalizeAll;
  return fn(inputs, workdir);
}

type VerifyPaymentFn = typeof realVerifyPayment;
let verifyPaymentOverride: VerifyPaymentFn | null = null;

/** Overrides verifyPayment in tests (avoids real RPC calls). */
export function setPaymentVerifierForTesting(fn: VerifyPaymentFn | null): void {
  verifyPaymentOverride = fn;
}

function runVerifyPayment(
  params: Parameters<VerifyPaymentFn>[0],
): ReturnType<VerifyPaymentFn> {
  const fn = verifyPaymentOverride ?? realVerifyPayment;
  return fn(params);
}

/**
 * Authenticate the agent callback. Accepts either:
 *  - X-Agent-Signature: sha256=<hex>  (HMAC-SHA256 over the raw request body
 *    keyed by AGENT_CALLBACK_TOKEN), or
 *  - X-Agent-Token: <token>           (legacy shared-secret).
 *
 * In production and when AGENT_HMAC_REQUIRED=true, the legacy header is
 * rejected and the signature is required.
 */
function verifyAgentAuth(req: {
  header: (name: string) => string | undefined;
  rawBody?: Buffer;
}): { ok: boolean; reason?: string } {
  const sigHeader = req.header('x-agent-signature') ?? '';
  const tokenHeader = req.header('x-agent-token') ?? '';
  const hmacRequired = config.agentHmacRequired || config.nodeEnv === 'production';

  if (sigHeader) {
    const match = /^sha256=([0-9a-fA-F]+)$/.exec(sigHeader);
    if (!match) return { ok: false, reason: 'Malformed X-Agent-Signature header' };
    const provided = Buffer.from(match[1] ?? '', 'hex');
    const body = (req as { rawBody?: Buffer }).rawBody ?? Buffer.alloc(0);
    const expected = createHmac('sha256', config.agentCallbackToken).update(body).digest();
    if (provided.length !== expected.length) {
      return { ok: false, reason: 'Invalid signature' };
    }
    if (!timingSafeEqual(provided, expected)) {
      return { ok: false, reason: 'Invalid signature' };
    }
    return { ok: true };
  }

  if (hmacRequired) {
    return { ok: false, reason: 'X-Agent-Signature required' };
  }

  if (!tokenHeader) return { ok: false, reason: 'Missing X-Agent-Token' };
  // Timing-safe compare on the shared secret.
  const a = Buffer.from(tokenHeader);
  const b = Buffer.from(config.agentCallbackToken);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return { ok: false, reason: 'Invalid agent token' };
  }
  return { ok: true };
}

const router = Router();

/**
 * POST /api/audit — create a submission.
 *
 * Two accepted request shapes:
 *  - New (P4.6):  { targets: Target[], email }  → N AuditTasks under one AuditBatch
 *  - Legacy:     { inputs: AuditInput[], email } → single AuditTask wrapped in a 1-target batch
 *
 * Response (batch-shaped in both cases):
 *   { batchId, taskIds, status, paymentUrl, paymentReference,
 *     recipient, amountSol, cluster, expiresAt, freeAudit? }
 */
router.post('/audit', async (req, res, next) => {
  try {
    const taskStore = getTaskStore();
    const batchStore = getBatchStore();

    const rawBody = req.body as Record<string, unknown> | undefined;
    const hasTargets = Array.isArray(rawBody?.targets);

    // Parse into a uniform `perTaskInputs: AuditInput[][]`.
    let perTaskInputs: AuditTask['inputs'][] = [];
    let email: string;
    if (hasTargets) {
      const parsed = createBatchSchema.parse(req.body);
      email = parsed.email;
      perTaskInputs = parsed.targets.map((t) => targetToInputs(t) as AuditTask['inputs']);
    } else {
      const parsed = createAuditSchema.parse(req.body);
      email = parsed.email;
      perTaskInputs = [parsed.inputs];
    }

    const now = new Date().toISOString();
    const batchId = randomUUID();
    const taskIds = perTaskInputs.map(() => randomUUID());
    const totalAmountSol = +(config.auditPriceSol * perTaskInputs.length).toFixed(9);

    // Build the N task skeletons up front so we can crea them atomically
    // after payment config is validated.
    const buildTaskSkeleton = (idx: number, status: TaskStatus): AuditTask => ({
      taskId: taskIds[idx] as string,
      batchId,
      inputs: perTaskInputs[idx] as AuditTask['inputs'],
      email,
      status,
      createdAt: now,
      updatedAt: now,
    });

    if (config.freeAudit) {
      const batch: AuditBatch = {
        batchId,
        taskIds,
        email,
        status: 'paid',
        totalAmountSol: 0,
        cluster: config.solanaCluster,
        freeAudit: true,
        createdAt: now,
        updatedAt: now,
      };
      await batchStore.create(batch);

      for (let i = 0; i < taskIds.length; i++) {
        const task = buildTaskSkeleton(i, 'paid');
        task.progress = 'FREE_AUDIT enabled, normalizing inputs...';
        await taskStore.create(task);
        logTaskEvent('info', task.taskId, 'task created (free-audit path)', {
          batchId,
          inputs: task.inputs.length,
          email: task.email,
        });
        // Lark Stage 1 · submitted (FREE_AUDIT path — fire-and-forget).
        void notifyScanRequested(task).catch((err) =>
          logger.warn({ err, taskId: task.taskId, batchId }, 'lark submitted notify failed'),
        );
        void normalizeAndEnqueue(task.taskId);
      }

      res.status(201).json({
        batchId,
        taskIds,
        // `taskId` is a back-compat alias (= taskIds[0]) for pre-P4.6
        // clients that expected a single-task response shape.
        taskId: taskIds[0],
        status: batch.status,
        amountSol: 0,
        cluster: config.solanaCluster,
        freeAudit: true,
      });
      return;
    }

    if (!isPaymentConfigured()) {
      res.status(503).json({
        code: 'PAYMENT_NOT_CONFIGURED',
        message: 'Service wallet is not configured; set SOLANA_SERVICE_WALLET or FREE_AUDIT=true.',
      });
      return;
    }

    const payment = createPaymentRequest({
      taskId: batchId,
      amountSol: totalAmountSol,
      label: 'SolGuard Security Audit',
      message:
        taskIds.length === 1
          ? `Audit batch ${batchId}`
          : `Audit batch ${batchId} (${taskIds.length} targets)`,
    });

    const batch: AuditBatch = {
      batchId,
      taskIds,
      email,
      status: 'paying',
      totalAmountSol: payment.amountSol,
      paymentReference: payment.reference,
      paymentRecipient: payment.recipient,
      paymentUrl: payment.url,
      paymentExpiresAt: payment.expiresAt,
      cluster: config.solanaCluster,
      createdAt: now,
      updatedAt: now,
    };
    await batchStore.create(batch);

    for (let i = 0; i < taskIds.length; i++) {
      const task = buildTaskSkeleton(i, 'paying');
      // Mirror batch-level payment fields onto each task so existing
      // single-task endpoints (polling, manual signature push) keep working.
      task.paymentReference = payment.reference;
      task.paymentRecipient = payment.recipient;
      task.paymentAmountSol = payment.amountSol;
      task.paymentUrl = payment.url;
      task.paymentExpiresAt = payment.expiresAt;
      await taskStore.create(task);
      logTaskEvent('info', task.taskId, 'task created (awaiting payment)', {
        batchId,
        inputs: task.inputs.length,
        amountSol: payment.amountSol,
        cluster: config.solanaCluster,
      });
      void notifyScanRequested(task).catch((err) =>
        logger.warn({ err, taskId: task.taskId, batchId }, 'lark submitted notify failed'),
      );
    }

    res.status(201).json({
      batchId,
      taskIds,
      taskId: taskIds[0],
      status: batch.status,
      paymentUrl: payment.url,
      paymentReference: payment.reference,
      recipient: payment.recipient,
      amountSol: payment.amountSol,
      cluster: config.solanaCluster,
      expiresAt: payment.expiresAt,
    });
  } catch (err) {
    next(err);
  }
});

/**
 * GET /api/audit/batch/:batchId — aggregate view of a batch plus its tasks.
 * Used by the frontend progress/report pages to show per-Target progress
 * bars and tabs.
 */
router.get('/audit/batch/:batchId', async (req, res, next) => {
  try {
    const batchStore = getBatchStore();
    const taskStore = getTaskStore();
    const batchId = req.params.batchId ?? '';
    const batch = await batchStore.get(batchId);
    if (!batch) {
      res.status(404).json({ code: 'NOT_FOUND', message: 'Batch not found' });
      return;
    }

    const tasks: AuditTask[] = [];
    for (const id of batch.taskIds) {
      const t = await taskStore.get(id);
      if (!t) continue;
      const snap: AuditTask = { ...t };
      if (snap.status !== 'completed') {
        delete snap.reportMarkdown;
      }
      tasks.push(snap);
    }

    res.json({ batch, tasks });
  } catch (err) {
    next(err);
  }
});

/**
 * POST /api/audit/batch/:batchId/payment — client-pushed signature covering
 * the full batch amount. On success flips ALL batch tasks paying → paid and
 * enqueues each for normalization/audit.
 */
router.post('/audit/batch/:batchId/payment', async (req, res, next) => {
  try {
    const batchStore = getBatchStore();
    const taskStore = getTaskStore();
    const batchId = req.params.batchId ?? '';
    const batch = await batchStore.get(batchId);
    if (!batch) {
      res.status(404).json({ code: 'NOT_FOUND', message: 'Batch not found' });
      return;
    }

    if (batch.status !== 'paying') {
      res.status(409).json({
        code: 'INVALID_STATE',
        message: `Batch is in status "${batch.status}"; payment push only valid while "paying".`,
      });
      return;
    }

    const { signature } = paymentPushSchema.parse(req.body);

    if (!batch.paymentReference || !batch.paymentRecipient || !batch.totalAmountSol) {
      res.status(409).json({
        code: 'PAYMENT_NOT_READY',
        message: 'Batch has no outstanding payment request',
      });
      return;
    }

    const verdict = await runVerifyPayment({
      connection: getConnection(),
      signature,
      reference: batch.paymentReference,
      recipient: batch.paymentRecipient,
      amountSol: batch.totalAmountSol,
    });

    if (!verdict.ok) {
      res.status(200).json({ ok: false, error: verdict.error });
      return;
    }

    const now = new Date().toISOString();
    await batchStore.update(batchId, {
      status: 'paid',
      paymentSignature: signature,
      paymentConfirmedAt: now,
    });

    // Flip every task in the batch. Use a fresh paid snapshot for each
    // notification + normalize enqueue.
    for (const taskId of batch.taskIds) {
      try {
        const updated = await taskStore.update(taskId, {
          status: 'paid',
          paymentSignature: signature,
          progress: 'Payment confirmed, preparing audit...',
        });
        void notifyPaymentConfirmed(updated).catch((err) =>
          logger.warn({ err, taskId, batchId }, 'lark paid notify failed'),
        );
        void normalizeAndEnqueue(taskId).catch((err) => {
          logger.error({ err, taskId, batchId }, 'normalizeAndEnqueue (batch push) failed');
        });
      } catch (err) {
        logger.error({ err, taskId, batchId }, 'batch task flip to paid failed');
      }
    }

    logger.info({ batchId, signature, tasks: batch.taskIds.length }, 'batch payment confirmed via push');
    res.status(200).json({ ok: true, status: 'paid', signature });
  } catch (err) {
    next(err);
  }
});

router.get('/audit/:taskId', async (req, res, next) => {
  try {
    const store = getTaskStore();
    const task = await store.get(req.params.taskId ?? '');
    if (!task) {
      res.status(404).json({ code: 'NOT_FOUND', message: 'Task not found' });
      return;
    }

    const publicTask: AuditTask = { ...task };
    if (publicTask.status !== 'completed') {
      delete publicTask.reportMarkdown;
    }
    res.json(publicTask);
  } catch (err) {
    next(err);
  }
});

router.post('/audit/:taskId/complete', async (req, res, next) => {
  try {
    const store = getTaskStore();
    const auth = verifyAgentAuth(req);
    if (!auth.ok) {
      res.status(401).json({ code: 'UNAUTHORIZED', message: auth.reason });
      return;
    }

    const taskId = req.params.taskId ?? '';
    const existing = await store.get(taskId);
    if (!existing) {
      res.status(404).json({ code: 'NOT_FOUND', message: 'Task not found' });
      return;
    }

    const body = agentCompleteSchema.parse(req.body);

    const statusProvided = (body as { status?: TaskStatus }).status;
    const nextStatus: TaskStatus =
      statusProvided ?? (body.error ? 'failed' : 'completed');

    const patch: Partial<AuditTask> = {
      status: nextStatus,
      findings: body.findings as Finding[] | undefined,
      statistics: body.statistics as Statistics | undefined,
      reportMarkdown: body.reportMarkdown,
      reportUrl: body.reportUrl,
      error: body.error,
      completedAt: new Date().toISOString(),
      progress: nextStatus === 'completed' ? 'Audit completed.' : 'Audit failed.',
    };

    const updated = await store.update(taskId, patch);
    logger.info(
      { taskId, status: updated.status, findings: updated.findings?.length ?? 0 },
      'agent completion callback received',
    );
    logTaskEvent('info', taskId, 'agent completion callback received', {
      status: updated.status,
      findings: updated.findings?.length ?? 0,
      hasReport: Boolean(updated.reportMarkdown),
      error: updated.error,
    });

    // 触发后续交付 (邮件)
    const engine = getAuditEngine();
    engine.onAuditFinished(updated).catch((err) => {
      logger.error({ err, taskId }, 'onAuditFinished failed');
    });

    res.json({ ok: true, status: updated.status });
  } catch (err) {
    next(err);
  }
});

/**
 * Runs input normalization for a task (cloning repos, fetching bytecode,
 * extracting lead URLs) and, on success, forwards to the audit engine.
 * Designed to be fire-and-forget from the HTTP handler — any error is
 * surfaced on the task record itself rather than bubbled to the client.
 */
export async function normalizeAndEnqueue(taskId: string): Promise<void> {
  const store = getTaskStore();
  const task = await store.get(taskId);
  if (!task) {
    logger.error({ taskId }, 'normalizeAndEnqueue: task not found');
    return;
  }
  logTaskEvent('info', taskId, 'normalization started', {
    inputs: task.inputs.length,
    kinds: task.inputs.map((i) => i.type),
  });
  try {
    const workdir = getWorkdirFor(taskId);
    const { normalized, errors } = await runNormalize(task.inputs, workdir);
    if (normalized.length === 0) {
      logTaskEvent('error', taskId, 'normalization produced zero records', {
        errors,
      });
      await store.update(taskId, {
        status: 'failed',
        error:
          errors.length > 0
            ? `all inputs failed to normalize: ${errors.join('; ')}`
            : 'no inputs produced a normalized record',
        completedAt: new Date().toISOString(),
      });
      return;
    }
    const patch: Partial<AuditTask> = {
      normalizedInputs: normalized,
      progress: 'Dispatching audit runner...',
      progressPercent: 5,
    };
    if (errors.length > 0) {
      patch.normalizeError = errors.join('; ');
    }
    await store.update(taskId, patch);
    logTaskEvent('info', taskId, 'normalization succeeded; dispatching runner', {
      normalized: normalized.length,
      softErrors: errors.length,
    });
    const engine = getAuditEngine();
    engine.enqueue(taskId).catch((err) => {
      const msg = err instanceof Error ? err.message : String(err);
      logger.error({ err: msg, taskId }, 'audit enqueue failed');
      logTaskEvent('error', taskId, 'audit enqueue failed', { error: msg });
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    logger.error({ err: msg, taskId }, 'normalizeAndEnqueue crashed');
    logTaskEvent('error', taskId, 'normalization crashed', { error: msg });
    await store.update(taskId, {
      status: 'failed',
      error: `input normalization crashed: ${msg}`,
      completedAt: new Date().toISOString(),
    });
  }
}

/**
 * Client-pushed payment signature. Lets the frontend skip the 5s poller
 * latency by reporting the Phantom-signed tx directly. We verify on-chain
 * and on success flip status paying → paid and enqueue the audit pipeline.
 */
router.post('/audit/:taskId/payment', async (req, res, next) => {
  try {
    const taskStore = getTaskStore();
    const batchStore = getBatchStore();
    const taskId = req.params.taskId ?? '';
    const task = await taskStore.get(taskId);
    if (!task) {
      res.status(404).json({ code: 'NOT_FOUND', message: 'Task not found' });
      return;
    }

    if (task.status !== 'paying') {
      res.status(409).json({
        code: 'INVALID_STATE',
        message: `Task is in status "${task.status}"; payment push only valid while "paying".`,
      });
      return;
    }

    const { signature } = paymentPushSchema.parse(req.body);

    // If the task belongs to a batch, verify against the batch total and
    // propagate the payment to every sibling task.
    if (task.batchId) {
      const batch = await batchStore.get(task.batchId);
      if (
        !batch ||
        !batch.paymentReference ||
        !batch.paymentRecipient ||
        !batch.totalAmountSol
      ) {
        res.status(409).json({
          code: 'PAYMENT_NOT_READY',
          message: 'Batch has no outstanding payment request',
        });
        return;
      }
      if (batch.status !== 'paying') {
        res.status(409).json({
          code: 'INVALID_STATE',
          message: `Batch is in status "${batch.status}"; payment push only valid while "paying".`,
        });
        return;
      }
      const verdict = await runVerifyPayment({
        connection: getConnection(),
        signature,
        reference: batch.paymentReference,
        recipient: batch.paymentRecipient,
        amountSol: batch.totalAmountSol,
      });
      if (!verdict.ok) {
        res.status(200).json({ ok: false, error: verdict.error });
        return;
      }
      const now = new Date().toISOString();
      await batchStore.update(batch.batchId, {
        status: 'paid',
        paymentSignature: signature,
        paymentConfirmedAt: now,
      });
      for (const sibId of batch.taskIds) {
        try {
          const updated = await taskStore.update(sibId, {
            status: 'paid',
            paymentSignature: signature,
            progress: 'Payment confirmed, preparing audit...',
          });
          void notifyPaymentConfirmed(updated).catch((err) =>
            logger.warn({ err, taskId: sibId, batchId: batch.batchId }, 'lark paid notify failed'),
          );
          void normalizeAndEnqueue(sibId).catch((err) => {
            logger.error(
              { err, taskId: sibId, batchId: batch.batchId },
              'normalizeAndEnqueue (task-push→batch) failed',
            );
          });
        } catch (err) {
          logger.error(
            { err, taskId: sibId, batchId: batch.batchId },
            'sibling flip to paid failed',
          );
        }
      }
      logger.info(
        { taskId, batchId: batch.batchId, signature, siblings: batch.taskIds.length },
        'payment confirmed via task-push endpoint (batch mode)',
      );
      res.status(200).json({ ok: true, status: 'paid', signature });
      return;
    }

    // Legacy path: task without batchId (pre-P4.6). Verify per-task amount.
    if (!task.paymentReference || !task.paymentRecipient || task.paymentAmountSol === undefined) {
      res.status(409).json({
        code: 'PAYMENT_NOT_READY',
        message: 'Task has no outstanding payment request',
      });
      return;
    }

    const verdict = await runVerifyPayment({
      connection: getConnection(),
      signature,
      reference: task.paymentReference,
      recipient: task.paymentRecipient,
      amountSol: task.paymentAmountSol,
    });

    if (!verdict.ok) {
      res.status(200).json({ ok: false, error: verdict.error });
      return;
    }

    const updated = await taskStore.update(taskId, {
      status: 'paid',
      paymentSignature: signature,
      progress: 'Payment confirmed, preparing audit...',
    });
    logger.info({ taskId, signature }, 'payment confirmed via push endpoint (legacy)');

    void notifyPaymentConfirmed(updated).catch((err) =>
      logger.warn({ err, taskId }, 'lark paid notify failed'),
    );
    void normalizeAndEnqueue(taskId).catch((err) => {
      logger.error({ err, taskId }, 'normalizeAndEnqueue (push) failed');
    });

    res.status(200).json({ ok: true, status: 'paid', signature });
  } catch (err) {
    next(err);
  }
});

/** Sanitises a task record into the public-facing shape returned by the
 * report.json endpoint — strips email / tokens / raw normalizer artifacts. */
function toPublicReport(task: AuditTask): Record<string, unknown> {
  return {
    taskId: task.taskId,
    status: task.status,
    inputs: task.inputs,
    statistics: task.statistics,
    findings: task.findings,
    reportUrl: task.reportUrl,
    createdAt: task.createdAt,
    updatedAt: task.updatedAt,
    completedAt: task.completedAt,
    progress: task.progress,
    progressPercent: task.progressPercent,
  };
}

/** Downloads the Markdown audit report for a completed task. */
router.get('/audit/:taskId/report.md', async (req, res, next) => {
  try {
    const store = getTaskStore();
    const taskId = req.params.taskId ?? '';
    const task = await store.get(taskId);
    if (!task) {
      res.status(404).json({ code: 'NOT_FOUND', message: 'Task not found' });
      return;
    }
    if (task.status !== 'completed' || !task.reportMarkdown) {
      res.status(404).json({
        code: 'REPORT_NOT_READY',
        message: `Report not available (status: ${task.status})`,
      });
      return;
    }
    res.setHeader('Content-Type', 'text/markdown; charset=utf-8');
    res.setHeader(
      'Content-Disposition',
      `attachment; filename="solguard-${taskId}.md"`,
    );
    res.status(200).send(task.reportMarkdown);
  } catch (err) {
    next(err);
  }
});

/** JSON snapshot of a completed audit (findings + statistics + metadata). */
router.get('/audit/:taskId/report.json', async (req, res, next) => {
  try {
    const store = getTaskStore();
    const taskId = req.params.taskId ?? '';
    const task = await store.get(taskId);
    if (!task) {
      res.status(404).json({ code: 'NOT_FOUND', message: 'Task not found' });
      return;
    }
    if (task.status !== 'completed') {
      res.status(404).json({
        code: 'REPORT_NOT_READY',
        message: `Report not available (status: ${task.status})`,
      });
      return;
    }
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.status(200).json(toPublicReport(task));
  } catch (err) {
    next(err);
  }
});

export default router;
