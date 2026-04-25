// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { existsSync, readFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { after, describe, it } from 'node:test';
import request from 'supertest';
import { config } from '../config';
import { createApp } from '../server';

const app = createApp();
const dataDir = path.resolve(config.dataDir);

after(() => {
  const file = path.join(dataDir, 'feedback.jsonl');
  if (existsSync(file)) rmSync(file);
});

describe('POST /api/feedback', () => {
  it('appends valid feedback to jsonl', async () => {
    await request(app)
      .post('/api/feedback')
      .send({ rating: 5, content: 'great', email: 'u@example.com' })
      .expect(201);

    const file = path.join(dataDir, 'feedback.jsonl');
    assert.ok(existsSync(file));
    const line = readFileSync(file, 'utf8').trim().split('\n').pop();
    assert.ok(line);
    const parsed = JSON.parse(line!);
    assert.equal(parsed.rating, 5);
    assert.equal(parsed.content, 'great');
    assert.ok(parsed.receivedAt);
  });

  it('rejects invalid rating', async () => {
    await request(app).post('/api/feedback').send({ rating: 99 }).expect(400);
  });
});
