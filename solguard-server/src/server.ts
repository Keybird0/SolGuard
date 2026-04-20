// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import path from 'node:path';
import cors from 'cors';
import express from 'express';
import pinoHttp from 'pino-http';
import { config } from './config';
import { logger } from './logger';
import { errorHandler, notFoundHandler } from './middleware/error-handler';
import auditRouter from './routes/audit';
import healthRouter from './routes/health';

export function createApp(): express.Express {
  const app = express();

  app.use(
    pinoHttp({
      logger,
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
  app.use(express.json({ limit: '1mb' }));
  app.use(express.urlencoded({ extended: true, limit: '1mb' }));

  app.use(express.static(path.join(__dirname, '..', 'public')));

  app.use('/', healthRouter);
  app.use('/api', auditRouter);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}

function main(): void {
  const app = createApp();
  app.listen(config.port, () => {
    logger.info(
      {
        port: config.port,
        env: config.nodeEnv,
        version: config.appVersion,
      },
      '🛡️  SolGuard server listening',
    );
  });
}

if (require.main === module) {
  main();
}
