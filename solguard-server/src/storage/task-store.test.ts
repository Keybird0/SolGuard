// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, it } from 'node:test';
import { FileJsonTaskStore } from './file-json-task-store';
import { InMemoryTaskStore, type TaskStore } from './task-store';
import type { AuditTask } from '../types';

function sampleTask(id: string): AuditTask {
  const now = new Date().toISOString();
  return {
    taskId: id,
    inputs: [{ type: 'github', value: 'https://github.com/a/b' }],
    email: 'u@example.com',
    status: 'pending',
    createdAt: now,
    updatedAt: now,
  };
}

function runStoreSuite(name: string, factory: () => TaskStore): void {
  describe(`TaskStore: ${name}`, () => {
    let store: TaskStore;

    beforeEach(() => {
      store = factory();
    });

    it('creates and retrieves a task', async () => {
      const task = sampleTask('t1');
      await store.create(task);
      const got = await store.get('t1');
      assert.equal(got?.taskId, 't1');
    });

    it('rejects duplicate create', async () => {
      await store.create(sampleTask('dup'));
      await assert.rejects(() => store.create(sampleTask('dup')));
    });

    it('updates and bumps updatedAt', async () => {
      await store.create(sampleTask('u1'));
      const first = await store.get('u1');
      await new Promise((r) => setTimeout(r, 5));
      const updated = await store.update('u1', { status: 'scanning', progress: 'go' });
      assert.equal(updated.status, 'scanning');
      assert.equal(updated.progress, 'go');
      assert.notEqual(updated.updatedAt, first?.updatedAt);
    });

    it('lists filtered by status', async () => {
      await store.create({ ...sampleTask('a'), status: 'paying' });
      await store.create({ ...sampleTask('b'), status: 'completed' });
      const paying = await store.list({ status: 'paying' });
      assert.equal(paying.length, 1);
      assert.equal(paying[0]?.taskId, 'a');
    });

    it('handles concurrent creates without losing data', async () => {
      const ids = Array.from({ length: 100 }, (_, i) => `c${i}`);
      await Promise.all(ids.map((id) => store.create(sampleTask(id))));
      const all = await store.list({});
      assert.equal(all.length, 100);
    });
  });
}

runStoreSuite('in-memory', () => new InMemoryTaskStore());

describe('FileJsonTaskStore persistence', () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), 'solguard-tasks-'));
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it('persists across instances', async () => {
    const first = new FileJsonTaskStore(dir);
    await first.create(sampleTask('persist'));
    const second = new FileJsonTaskStore(dir);
    const got = await second.get('persist');
    assert.equal(got?.taskId, 'persist');
  });
});

runStoreSuite('file-json', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'solguard-tasks-suite-'));
  return new FileJsonTaskStore(dir);
});
