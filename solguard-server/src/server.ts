// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import cors from 'cors';
import express from 'express';
import pinoHttp from 'pino-http';
import { getAuditEngine } from './audit-engine';
import { config } from './config';
import { logger } from './logger';
import { errorHandler, notFoundHandler } from './middleware/error-handler';
import { createRateLimiter } from './middleware/rate-limit';
import { startPaymentPoller } from './payment-poller';
import adminRouter from './routes/admin';
import auditRouter, { normalizeAndEnqueue } from './routes/audit';
import feedbackRouter from './routes/feedback';
import healthRouter from './routes/health';
import { getTaskStore } from './storage/task-store';

export function createApp(): express.Express {
  const app = express();

  app.use(
    pinoHttp({
      logger,
      // Respect an inbound X-Request-Id for tracing across proxies /
      // client retries; else mint a fresh uuid so every log frame in
      // this request carries a stable `req.id`.
      genReqId: (req, res) => {
        const incoming = req.headers['x-request-id'];
        const reqId = typeof incoming === 'string' && incoming ? incoming : randomUUID();
        res.setHeader('X-Request-Id', reqId);
        return reqId;
      },
      customLogLevel: (_req, res, err) => {
        if (err || res.statusCode >= 500) return 'error';
        if (res.statusCode >= 400) return 'warn';
        return 'info';
      },
    }),
  );
  app.use(
    cors({
      origin: (origin, cb) => {
        if (!origin || config.corsOrigins.includes(origin) || config.corsOrigins.includes('*')) {
          cb(null, true);
          return;
        }
        cb(new Error(`CORS: origin ${origin} not allowed`));
      },
      credentials: true,
    }),
  );
  app.use(
    express.json({
      limit: '1mb',
      // Stash the raw request body on req.rawBody so the HMAC verifier
      // (used by POST /api/audit/:id/complete) can compute a signature
      // over the exact bytes the client sent.
      verify: (req, _res, buf) => {
        (req as unknown as { rawBody?: Buffer }).rawBody = Buffer.from(buf);
      },
    }),
  );
  app.use(express.urlencoded({ extended: true, limit: '1mb' }));

  app.use(express.static(path.join(__dirname, '..', 'public')));

  // Rate limiter applied to the two user-facing POST endpoints. It's a
  // no-op when RATE_LIMIT_ENABLED=false (the default outside production).
  const rateLimiter = createRateLimiter();
  app.use('/api/audit', (req, res, next) => {
    if (req.method === 'POST' && req.path === '/') return rateLimiter(req, res, next);
    next();
  });
  app.use('/api/feedback', (req, res, next) => {
    if (req.method === 'POST') return rateLimiter(req, res, next);
    next();
  });

  app.use('/', healthRouter);
  app.use('/api', auditRouter);
  app.use('/api', feedbackRouter);
  app.use('/api', adminRouter);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}

function main(): void {
  const app = createApp();
  const store = getTaskStore();
  const engine = getAuditEngine({ store });

  if (!config.freeAudit) {
    startPaymentPoller({
      store,
      onPaid: (task) => {
        void normalizeAndEnqueue(task.taskId).catch((err) => {
          logger.error({ err, taskId: task.taskId }, 'normalizeAndEnqueue failed');
        });
      },
    });
    logger.info({ intervalMs: config.paymentPollIntervalMs }, 'payment poller started');
  } else {
    logger.warn('FREE_AUDIT enabled: skipping payment poller');
  }
  // Reference the engine so lint doesn't complain when FREE_AUDIT skips
  // the poller; normalizeAndEnqueue will re-resolve the engine anyway.
  void engine;

  app.listen(config.port, () => {
    logger.info(
      {
        port: config.port,
        env: config.nodeEnv,
        version: config.appVersion,
        freeAudit: config.freeAudit,
        cluster: config.solanaCluster,
      },
      'SolGuard server listening',
    );
  });
}

if (require.main === module) {
  main();
}
