// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// Poll on-chain confirmation for pending audit payments. As of P4.6 the
// canonical unit is the AuditBatch (one reference / one signature / one
// amount covering N sibling tasks), but we still poll legacy tasks that
// have a `paying` status without a batchId for upgrade-safety.
import { PublicKey } from '@solana/web3.js';
import { getAuditEngine } from './audit-engine';
import { config } from './config';
import { logger } from './logger';
import { notifyPaymentConfirmed } from './notify/lark';
import { findPaymentSignature, getConnection, verifyPayment } from './payment';
import type { BatchStore } from './storage/batch-store';
import type { TaskStore } from './storage/task-store';
import { getBatchStore } from './storage/batch-store';
import type { AuditBatch, AuditTask } from './types';

export interface PaymentPollerOptions {
  store: TaskStore;
  batchStore?: BatchStore;
  onPaid: (task: AuditTask) => void;
  intervalMs?: number;
}

export interface PaymentPollerHandle {
  stop(): void;
  tick(): Promise<void>;
}

export function startPaymentPoller(opts: PaymentPollerOptions): PaymentPollerHandle {
  const intervalMs = opts.intervalMs ?? config.paymentPollIntervalMs;
  const batchStore = opts.batchStore ?? getBatchStore();
  let timer: NodeJS.Timeout | null = null;
  let running = false;

  async function tick(): Promise<void> {
    if (running) return;
    running = true;
    try {
      const connection = getConnection();

      const batches = await batchStore.list({ status: 'paying' });
      for (const batch of batches) {
        await processBatch(batch, batchStore, opts.store, connection, opts.onPaid);
      }

      // Legacy fallback: any `paying` task not tied to a batch (should be
      // zero after the P4.6 migration; kept for resilience).
      const orphanTasks = (await opts.store.list({ status: 'paying' })).filter(
        (t) => !t.batchId,
      );
      for (const task of orphanTasks) {
        await processLegacyTask(task, opts.store, connection, opts.onPaid);
      }
    } catch (err) {
      logger.error({ err }, 'payment poller tick failed');
    } finally {
      running = false;
    }
  }

  timer = setInterval(() => {
    void tick();
  }, intervalMs);
  timer.unref?.();

  return {
    stop(): void {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    },
    tick,
  };
}

async function processBatch(
  batch: AuditBatch,
  batchStore: BatchStore,
  taskStore: TaskStore,
  connection: ReturnType<typeof getConnection>,
  onPaid: (task: AuditTask) => void,
): Promise<void> {
  if (!batch.paymentReference || !batch.paymentRecipient || !batch.totalAmountSol) {
    return;
  }

  if (batch.paymentExpiresAt && Date.parse(batch.paymentExpiresAt) < Date.now()) {
    logger.warn({ batchId: batch.batchId }, 'batch payment expired, marking failed');
    const now = new Date().toISOString();
    await batchStore.update(batch.batchId, { status: 'failed' });
    for (const taskId of batch.taskIds) {
      try {
        const failed = await taskStore.update(taskId, {
          status: 'failed',
          error: 'Payment timed out before confirmation.',
          completedAt: now,
        });
        getAuditEngine()
          .onAuditFinished(failed)
          .catch((err) =>
            logger.warn(
              { err, taskId, batchId: batch.batchId },
              'onAuditFinished (payment-timeout) failed',
            ),
          );
      } catch (err) {
        logger.error(
          { err, taskId, batchId: batch.batchId },
          'failed to mark batch task as failed on payment timeout',
        );
      }
    }
    return;
  }

  try {
    const ref = new PublicKey(batch.paymentReference);
    const sigInfo = await findPaymentSignature(connection, ref);
    if (!sigInfo) return;

    const verdict = await verifyPayment({
      connection,
      signature: sigInfo.signature,
      reference: batch.paymentReference,
      recipient: batch.paymentRecipient,
      amountSol: batch.totalAmountSol,
    });

    if (!verdict.ok) {
      logger.warn(
        { batchId: batch.batchId, err: verdict.error },
        'found batch reference but transfer invalid; waiting for next valid tx',
      );
      return;
    }

    const confirmedAt = new Date().toISOString();
    await batchStore.update(batch.batchId, {
      status: 'paid',
      paymentSignature: sigInfo.signature,
      paymentConfirmedAt: confirmedAt,
    });

    logger.info(
      { batchId: batch.batchId, signature: sigInfo.signature, tasks: batch.taskIds.length },
      'batch payment verified, launching audit(s)',
    );

    for (const taskId of batch.taskIds) {
      try {
        const updated = await taskStore.update(taskId, {
          status: 'paid',
          paymentSignature: sigInfo.signature,
          progress: 'Payment confirmed, preparing audit...',
        });
        void notifyPaymentConfirmed(updated).catch((err) =>
          logger.warn(
            { err, taskId, batchId: batch.batchId },
            'lark paid notify failed',
          ),
        );
        try {
          onPaid(updated);
        } catch (err) {
          logger.error(
            { err, taskId, batchId: batch.batchId },
            'onPaid handler threw (batch task)',
          );
        }
      } catch (err) {
        logger.error(
          { err, taskId, batchId: batch.batchId },
          'failed to flip batch task to paid',
        );
      }
    }
  } catch (err) {
    logger.error({ err, batchId: batch.batchId }, 'processBatch failed');
  }
}

async function processLegacyTask(
  task: AuditTask,
  taskStore: TaskStore,
  connection: ReturnType<typeof getConnection>,
  onPaid: (task: AuditTask) => void,
): Promise<void> {
  if (!task.paymentReference || !task.paymentRecipient || !task.paymentAmountSol) {
    return;
  }

  if (task.paymentExpiresAt && Date.parse(task.paymentExpiresAt) < Date.now()) {
    logger.warn({ taskId: task.taskId }, 'legacy task payment expired, marking failed');
    const failed = await taskStore.update(task.taskId, {
      status: 'failed',
      error: 'Payment timed out before confirmation.',
      completedAt: new Date().toISOString(),
    });
    getAuditEngine()
      .onAuditFinished(failed)
      .catch((err) =>
        logger.warn(
          { err, taskId: task.taskId },
          'onAuditFinished (payment-timeout legacy) failed',
        ),
      );
    return;
  }

  try {
    const ref = new PublicKey(task.paymentReference);
    const sigInfo = await findPaymentSignature(connection, ref);
    if (!sigInfo) return;

    const verdict = await verifyPayment({
      connection,
      signature: sigInfo.signature,
      reference: task.paymentReference,
      recipient: task.paymentRecipient,
      amountSol: task.paymentAmountSol,
    });

    if (!verdict.ok) {
      logger.warn(
        { taskId: task.taskId, err: verdict.error },
        'legacy task: reference found but transfer invalid',
      );
      return;
    }

    const updated = await taskStore.update(task.taskId, {
      status: 'paid',
      paymentSignature: sigInfo.signature,
      progress: 'Payment confirmed, preparing audit...',
    });
    logger.info(
      { taskId: task.taskId, signature: sigInfo.signature },
      'legacy task payment verified, launching audit',
    );
    void notifyPaymentConfirmed(updated).catch((err) =>
      logger.warn({ err, taskId: task.taskId }, 'lark paid notify failed'),
    );
    try {
      onPaid(updated);
    } catch (err) {
      logger.error({ err, taskId: task.taskId }, 'onPaid handler threw (legacy task)');
    }
  } catch (err) {
    logger.error({ err, taskId: task.taskId }, 'processLegacyTask failed');
  }
}
