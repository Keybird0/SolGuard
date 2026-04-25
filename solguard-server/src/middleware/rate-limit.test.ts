// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { describe, it } from 'node:test';
import express from 'express';
import request from 'supertest';
import { createRateLimiter } from './rate-limit';

describe('createRateLimiter', () => {
  it('no-ops when disabled', async () => {
    const app = express();
    app.use(createRateLimiter({ enabled: false, max: 1, windowMs: 60_000 }));
    app.get('/', (_req, res) => {
      res.json({ ok: true });
    });
    await request(app).get('/').expect(200);
    await request(app).get('/').expect(200);
    await request(app).get('/').expect(200);
  });

  it('returns 429 after exceeding max within window', async () => {
    const app = express();
    app.use(createRateLimiter({ enabled: true, max: 2, windowMs: 60_000 }));
    app.get('/', (_req, res) => {
      res.json({ ok: true });
    });
    await request(app).get('/').expect(200);
    await request(app).get('/').expect(200);
    const res = await request(app).get('/').expect(429);
    assert.equal(res.body.code, 'RATE_LIMITED');
    assert.ok(res.headers['retry-after']);
  });

  it('uses a custom keyFor to segregate buckets', async () => {
    const app = express();
    let which = 'A';
    app.use(createRateLimiter({ enabled: true, max: 1, windowMs: 60_000, keyFor: () => which }));
    app.get('/', (_req, res) => {
      res.json({ ok: true });
    });
    await request(app).get('/').expect(200); // A: 1
    await request(app).get('/').expect(429); // A: 2 → over
    which = 'B';
    await request(app).get('/').expect(200); // B: 1
  });
});
