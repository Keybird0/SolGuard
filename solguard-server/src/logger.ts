import pino from 'pino';
import { config } from './config';

const isDev = config.nodeEnv === 'development';

export const logger = pino({
  level: config.logLevel,
  ...(isDev && {
    transport: {
      target: 'pino-pretty',
      options: {
        colorize: true,
        translateTime: 'HH:MM:ss.l',
        ignore: 'pid,hostname',
      },
    },
  }),
  redact: {
    paths: ['req.headers.authorization', 'req.headers["x-agent-token"]', '*.smtpPass', '*.apiKey'],
    censor: '[REDACTED]',
  },
});
