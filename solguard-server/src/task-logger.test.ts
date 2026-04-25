// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { existsSync, readFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { after, before, describe, it } from 'node:test';
import express from 'express';
import request from 'supertest';
import { appendTaskLog, logTaskEvent, readTaskLogTail, taskLogPath } from './task-logger';
import adminRouter from './routes/admin';

const LOG_DIR = path.resolve(process.cwd(), 'data-test/logs');

describe('task-logger', () => {
  before(() => {
    rmSync(LOG_DIR, { recursive: true, force: true });
  });
  after(() => {
    rmSync(LOG_DIR, { recursive: true, force: true });
  });

  it('rejects invalid taskIds', () => {
    assert.equal(taskLogPath(''), null);
    assert.equal(taskLogPath('../etc/passwd'), null);
    assert.equal(taskLogPath('bad/id'), null);
    assert.equal(taskLogPath('with space'), null);
  });

  it('accepts safe taskIds and writes JSON frames', () => {
    const id = 'abc_123.test-ID';
    appendTaskLog(id, { msg: 'hello', extra: 42 });
    const p = taskLogPath(id);
    assert.ok(p && existsSync(p));
    const content = readFileSync(p, 'utf8').trim();
    const frame = JSON.parse(content);
    assert.equal(frame.taskId, id);
    assert.equal(frame.msg, 'hello');
    assert.equal(frame.extra, 42);
    assert.equal(typeof frame.time, 'number');
  });

  it('logTaskEvent writes to the per-task file', () => {
    const id = 'evt-001';
    logTaskEvent('info', id, 'phase started', { phase: 'normalize' });
    const tail = readTaskLogTail(id) ?? '';
    const frame = JSON.parse(tail.trim().split('\n').pop() ?? '{}');
    assert.equal(frame.taskId, id);
    assert.equal(frame.phase, 'normalize');
    assert.equal(frame.msg, 'phase started');
  });

  it('readTaskLogTail returns null for unknown ids', () => {
    assert.equal(readTaskLogTail('no-such-task'), null);
  });
});

describe('admin logs route', () => {
  const app = express();
  app.use('/api', adminRouter);

  it('rejects missing admin token', async () => {
    const res = await request(app).get('/api/admin/logs/any').expect(401);
    assert.equal(res.body.code, 'UNAUTHORIZED');
  });

  it('rejects malformed taskId', async () => {
    const res = await request(app)
      .get('/api/admin/logs/has%20space')
      .set('x-admin-token', 'test-admin-token-42')
      .expect(400);
    assert.equal(res.body.code, 'BAD_TASK_ID');
  });

  it('returns tail for valid taskId', async () => {
    const id = 'admin-logs-abc';
    appendTaskLog(id, { msg: 'hello from route test' });
    const res = await request(app)
      .get(`/api/admin/logs/${id}`)
      .set('x-admin-token', 'test-admin-token-42')
      .expect(200);
    assert.match(res.text, /hello from route test/);
    assert.ok(res.text.includes('"taskId":"admin-logs-abc"'));
  });

  it('rejects invalid admin token', async () => {
    const id = 'admin-logs-auth';
    appendTaskLog(id, { msg: 'secret' });
    const res = await request(app)
      .get(`/api/admin/logs/${id}`)
      .set('x-admin-token', 'wrong-token')
      .expect(401);
    assert.equal(res.body.code, 'UNAUTHORIZED');
  });

  it('returns 404 for unknown taskId', async () => {
    const res = await request(app)
      .get('/api/admin/logs/never-written')
      .set('x-admin-token', 'test-admin-token-42')
      .expect(404);
    assert.equal(res.body.code, 'NOT_FOUND');
  });
});
