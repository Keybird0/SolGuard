// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import type { RequestHandler } from 'express';
import { config } from '../config';
import { logger } from '../logger';

interface Bucket {
  /** Monotonically-sliding window of request epoch-ms timestamps. */
  hits: number[];
}

export interface RateLimitOptions {
  windowMs?: number;
  max?: number;
  /** Custom key extractor; defaults to request IP. */
  keyFor?: (req: Parameters<RequestHandler>[0]) => string;
  /** Override for the enabled flag (testing). */
  enabled?: boolean;
}

/**
 * Sliding-window in-memory rate limiter. Suitable for single-node dev;
 * for multi-node deployment swap for Redis / upstash.
 */
export function createRateLimiter(opts: RateLimitOptions = {}): RequestHandler {
  const windowMs = opts.windowMs ?? config.rateLimitWindowMs;
  const max = opts.max ?? config.rateLimitMaxRequests;
  const enabled = opts.enabled ?? config.rateLimitEnabled;
  const keyFor =
    opts.keyFor ??
    ((req) => (req.ip ?? req.socket.remoteAddress ?? 'unknown'));

  const buckets = new Map<string, Bucket>();

  const handler: RequestHandler = (req, res, next) => {
    if (!enabled) {
      next();
      return;
    }
    const key = keyFor(req);
    const now = Date.now();
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { hits: [] };
      buckets.set(key, bucket);
    }
    // Evict timestamps older than the window.
    const cutoff = now - windowMs;
    bucket.hits = bucket.hits.filter((t) => t >= cutoff);

    if (bucket.hits.length >= max) {
      const retryAfterMs = Math.max(0, (bucket.hits[0] ?? now) + windowMs - now);
      res.setHeader('Retry-After', Math.ceil(retryAfterMs / 1000).toString());
      logger.warn(
        { key, hits: bucket.hits.length, max, windowMs },
        'rate limit exceeded',
      );
      res.status(429).json({
        code: 'RATE_LIMITED',
        message: `Too many requests. Retry after ${Math.ceil(retryAfterMs / 1000)}s.`,
      });
      return;
    }

    bucket.hits.push(now);
    next();
  };

  return handler;
}
