import { randomUUID } from 'node:crypto';
import { Router } from 'express';
import { config } from '../config';
import { getTaskStore } from '../storage/task-store';
import type { AuditTask } from '../types';
import { createAuditSchema } from '../validators/audit';

const router = Router();
const store = getTaskStore();

router.post('/audit', async (req, res, next) => {
  try {
    const body = createAuditSchema.parse(req.body);
    const now = new Date().toISOString();
    const task: AuditTask = {
      taskId: randomUUID(),
      inputs: body.inputs,
      email: body.email,
      status: 'pending',
      paymentReference: randomUUID(),
      paymentAmountSol: config.auditPriceSol,
      createdAt: now,
      updatedAt: now,
    };
    await store.create(task);
    res.status(201).json({
      taskId: task.taskId,
      status: task.status,
      paymentReference: task.paymentReference,
      amountSol: task.paymentAmountSol,
      recipient: config.solanaServiceWallet ?? null,
    });
  } catch (err) {
    next(err);
  }
});

router.get('/audit/:taskId', async (req, res, next) => {
  try {
    const task = await store.get(req.params.taskId ?? '');
    if (!task) {
      res.status(404).json({ code: 'NOT_FOUND', message: 'Task not found' });
      return;
    }

    const publicTask = { ...task };
    if (publicTask.status !== 'completed') {
      delete publicTask.reportMarkdown;
    }
    res.json(publicTask);
  } catch (err) {
    next(err);
  }
});

export default router;
