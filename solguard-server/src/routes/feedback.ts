// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { appendFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { Router } from 'express';
import { config } from '../config';
import { logger } from '../logger';
import { feedbackSchema } from '../validators/audit';

const router = Router();

async function appendFeedback(record: unknown): Promise<void> {
  const dir = path.resolve(config.dataDir);
  await mkdir(dir, { recursive: true });
  const file = path.join(dir, 'feedback.jsonl');
  await appendFile(file, JSON.stringify(record) + '\n', 'utf8');
}

async function notifyWebhook(record: unknown): Promise<void> {
  if (!config.feedbackWebhookUrl) return;
  try {
    await fetch(config.feedbackWebhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'New SolGuard feedback', record }),
    });
  } catch (err) {
    logger.warn({ err }, 'feedback webhook failed');
  }
}

router.post('/feedback', async (req, res, next) => {
  try {
    const body = feedbackSchema.parse(req.body);
    const record = {
      ...body,
      receivedAt: new Date().toISOString(),
      ip: req.ip,
      userAgent: req.header('user-agent'),
    };
    await appendFeedback(record);
    notifyWebhook(record).catch(() => {
      /* already logged */
    });
    res.status(201).json({ ok: true });
  } catch (err) {
    next(err);
  }
});

export default router;
