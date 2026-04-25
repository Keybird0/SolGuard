// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { createHmac } from 'node:crypto';
import { after, describe, it } from 'node:test';
import request from 'supertest';
import { setAuditEngineForTesting, type AuditEngine } from '../audit-engine';
import { setMailerForTesting } from '../email';
import { createApp } from '../server';
import { setTaskStoreForTesting, InMemoryTaskStore } from '../storage/task-store';
import {
  setBatchStoreForTesting,
  InMemoryBatchStore,
} from '../storage/batch-store';
import { setNormalizerForTesting, setPaymentVerifierForTesting } from './audit';
import type { AuditTask, NormalizedInput } from '../types';

const store = new InMemoryTaskStore();
setTaskStoreForTesting(store);
const batchStore = new InMemoryBatchStore();
setBatchStoreForTesting(batchStore);

const fakeEngine: AuditEngine & { enqueued: string[]; finished: AuditTask[] } = {
  enqueued: [],
  finished: [],
  enqueue: async (taskId) => {
    fakeEngine.enqueued.push(taskId);
  },
  onAuditFinished: async (task) => {
    fakeEngine.finished.push(task);
  },
};
setAuditEngineForTesting(fakeEngine);
setMailerForTesting({ sendMail: async () => ({ ok: true }) });

// Stub the input normalizer so tests don't spawn real git/network calls.
setNormalizerForTesting(async (inputs) => ({
  normalized: inputs.map<NormalizedInput>((input) => ({
    kind: 'rust_source',
    rootDir: '/tmp/fake',
    primaryFile: '/tmp/fake/lib.rs',
    origin: input,
  })),
  errors: [],
}));

const app = createApp();

async function waitFor(cond: () => boolean, timeoutMs = 1000): Promise<void> {
  const start = Date.now();
  while (!cond()) {
    if (Date.now() - start > timeoutMs) return;
    await new Promise((r) => setTimeout(r, 10));
  }
}

after(() => {
  setAuditEngineForTesting(null);
  setTaskStoreForTesting(null);
  setBatchStoreForTesting(null);
  setMailerForTesting(null);
  setNormalizerForTesting(null);
  setPaymentVerifierForTesting(null);
});

describe('POST /api/audit (free audit)', () => {
  it('creates a task and enqueues audit', async () => {
    const res = await request(app)
      .post('/api/audit')
      .send({
        inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
        email: 'user@example.com',
      })
      .expect(201);

    assert.equal(res.body.status, 'paid');
    assert.equal(res.body.freeAudit, true);
    assert.ok(res.body.taskId);
    // normalizeAndEnqueue is fire-and-forget; wait one microtask tick.
    await waitFor(() => fakeEngine.enqueued.includes(res.body.taskId), 1000);
    assert.ok(fakeEngine.enqueued.includes(res.body.taskId));
  });

  it('rejects invalid payload', async () => {
    const res = await request(app)
      .post('/api/audit')
      .send({ inputs: [], email: 'not-an-email' })
      .expect(400);
    assert.equal(res.body.code, 'VALIDATION_ERROR');
  });
});

describe('GET /api/audit/:taskId', () => {
  it('returns 404 for unknown task', async () => {
    await request(app).get('/api/audit/does-not-exist').expect(404);
  });

  it('omits reportMarkdown for non-completed tasks', async () => {
    const created = await request(app)
      .post('/api/audit')
      .send({
        inputs: [{ type: 'website', value: 'https://solana.com' }],
        email: 'u@example.com',
      })
      .expect(201);
    await store.update(created.body.taskId, { reportMarkdown: '# secret' });
    const got = await request(app).get(`/api/audit/${created.body.taskId}`).expect(200);
    assert.equal(got.body.reportMarkdown, undefined);
  });
});

describe('POST /api/audit/:taskId/complete', () => {
  it('rejects without token', async () => {
    const created = await request(app)
      .post('/api/audit')
      .send({
        inputs: [{ type: 'website', value: 'https://solana.com' }],
        email: 'u@example.com',
      })
      .expect(201);
    await request(app)
      .post(`/api/audit/${created.body.taskId}/complete`)
      .send({ status: 'completed' })
      .expect(401);
  });

  it('accepts valid callback and flips status', async () => {
    const created = await request(app)
      .post('/api/audit')
      .send({
        inputs: [
          { type: 'contract_address', value: '4Nd1m6A8t3dV5Y5p7H5r2q6F9vJkL8m7n6W3u2X1Y4Z' },
        ],
        email: 'u@example.com',
      })
      .expect(201);

    const taskId = created.body.taskId;
    const res = await request(app)
      .post(`/api/audit/${taskId}/complete`)
      .set('X-Agent-Token', 'test-token')
      .send({
        status: 'completed',
        statistics: { critical: 1, high: 0, medium: 0, low: 0, info: 0, total: 1 },
        findings: [
          {
            id: 'F-001',
            severity: 'Critical',
            title: 'missing signer',
            location: 'handler.rs',
            description: 'no signer',
            impact: 'drain',
            recommendation: 'require signer',
          },
        ],
        reportMarkdown: '# Report',
      })
      .expect(200);

    assert.equal(res.body.status, 'completed');
    const stored = await store.get(taskId);
    assert.equal(stored?.status, 'completed');
    assert.equal(stored?.findings?.length, 1);
    assert.ok(fakeEngine.finished.some((t) => t.taskId === taskId));
  });
});

describe('POST /api/audit/:taskId/complete (HMAC)', () => {
  it('accepts a valid X-Agent-Signature', async () => {
    const created = await request(app)
      .post('/api/audit')
      .send({
        inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
        email: 'u@example.com',
      })
      .expect(201);
    const taskId = created.body.taskId;
    const body = { status: 'completed', reportMarkdown: '# ok' };
    const raw = Buffer.from(JSON.stringify(body));
    const sig = createHmac('sha256', 'test-token').update(raw).digest('hex');
    const res = await request(app)
      .post(`/api/audit/${taskId}/complete`)
      .set('Content-Type', 'application/json')
      .set('X-Agent-Signature', `sha256=${sig}`)
      .send(raw.toString('utf8'))
      .expect(200);
    assert.equal(res.body.status, 'completed');
  });

  it('rejects a tampered X-Agent-Signature', async () => {
    const created = await request(app)
      .post('/api/audit')
      .send({
        inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
        email: 'u@example.com',
      })
      .expect(201);
    const taskId = created.body.taskId;
    const body = { status: 'completed' };
    const raw = Buffer.from(JSON.stringify(body));
    const sig = createHmac('sha256', 'wrong-secret').update(raw).digest('hex');
    await request(app)
      .post(`/api/audit/${taskId}/complete`)
      .set('Content-Type', 'application/json')
      .set('X-Agent-Signature', `sha256=${sig}`)
      .send(raw.toString('utf8'))
      .expect(401);
  });
});

describe('POST /api/audit/:taskId/payment', () => {
  it('returns 404 for unknown task', async () => {
    await request(app).post('/api/audit/does-not-exist/payment').send({ signature: 'x'.repeat(64) }).expect(404);
  });

  it('rejects when task is not in "paying" state', async () => {
    // Free-audit tasks are created in state "paid", so the push endpoint
    // should reject with 409 INVALID_STATE.
    const created = await request(app)
      .post('/api/audit')
      .send({
        inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
        email: 'u@example.com',
      })
      .expect(201);
    const got = await request(app)
      .post(`/api/audit/${created.body.taskId}/payment`)
      .send({ signature: 'x'.repeat(64) })
      .expect(409);
    assert.equal(got.body.code, 'INVALID_STATE');
  });

  it('accepts valid push and flips status to paid', async () => {
    // Manually create a "paying" task in the store and mock verifyPayment.
    const taskId = 'push-task-001';
    const now = new Date().toISOString();
    await store.create({
      taskId,
      inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
      email: 'u@example.com',
      status: 'paying',
      paymentReference: 'Ref111111111111111111111111111111111111111',
      paymentRecipient: 'Rcpt11111111111111111111111111111111111111',
      paymentAmountSol: 0.001,
      createdAt: now,
      updatedAt: now,
    });
    setPaymentVerifierForTesting(async () => ({ ok: true, signature: 'sig1' }));
    const res = await request(app)
      .post(`/api/audit/${taskId}/payment`)
      .send({ signature: 'a'.repeat(64) })
      .expect(200);
    assert.equal(res.body.ok, true);
    assert.equal(res.body.status, 'paid');
    const stored = await store.get(taskId);
    assert.equal(stored?.status, 'paid');
    setPaymentVerifierForTesting(null);
  });

  it('returns ok:false and preserves status when on-chain verification fails', async () => {
    const taskId = 'push-task-002';
    const now = new Date().toISOString();
    await store.create({
      taskId,
      inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
      email: 'u@example.com',
      status: 'paying',
      paymentReference: 'Ref111111111111111111111111111111111111111',
      paymentRecipient: 'Rcpt11111111111111111111111111111111111111',
      paymentAmountSol: 0.001,
      createdAt: now,
      updatedAt: now,
    });
    setPaymentVerifierForTesting(async () => ({ ok: false, error: 'amount mismatch' }));
    const res = await request(app)
      .post(`/api/audit/${taskId}/payment`)
      .send({ signature: 'a'.repeat(64) })
      .expect(200);
    assert.equal(res.body.ok, false);
    const stored = await store.get(taskId);
    assert.equal(stored?.status, 'paying'); // unchanged
    setPaymentVerifierForTesting(null);
  });
});

describe('GET /api/audit/:taskId/report.md', () => {
  it('returns 404 for unknown task', async () => {
    await request(app).get('/api/audit/does-not-exist/report.md').expect(404);
  });

  it('returns 404 when task not completed', async () => {
    const created = await request(app)
      .post('/api/audit')
      .send({
        inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
        email: 'u@example.com',
      })
      .expect(201);
    const res = await request(app)
      .get(`/api/audit/${created.body.taskId}/report.md`)
      .expect(404);
    assert.equal(res.body.code, 'REPORT_NOT_READY');
  });

  it('serves markdown with attachment disposition when completed', async () => {
    const created = await request(app)
      .post('/api/audit')
      .send({
        inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
        email: 'u@example.com',
      })
      .expect(201);
    const taskId = created.body.taskId;
    await store.update(taskId, {
      status: 'completed',
      reportMarkdown: '# SolGuard\n\n- finding 1',
    });
    const res = await request(app).get(`/api/audit/${taskId}/report.md`).expect(200);
    assert.match(res.headers['content-type'] ?? '', /text\/markdown/);
    assert.match(res.headers['content-disposition'] ?? '', /attachment/);
    assert.equal(res.text, '# SolGuard\n\n- finding 1');
  });
});

describe('GET /api/audit/:taskId/report.json', () => {
  it('returns 404 for unknown task', async () => {
    await request(app).get('/api/audit/does-not-exist/report.json').expect(404);
  });

  it('returns 404 when task not completed', async () => {
    const created = await request(app)
      .post('/api/audit')
      .send({
        inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
        email: 'u@example.com',
      })
      .expect(201);
    await request(app).get(`/api/audit/${created.body.taskId}/report.json`).expect(404);
  });

  it('returns public snapshot without email / tokens when completed', async () => {
    const created = await request(app)
      .post('/api/audit')
      .send({
        inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
        email: 'secret@example.com',
      })
      .expect(201);
    const taskId = created.body.taskId;
    await store.update(taskId, {
      status: 'completed',
      statistics: { critical: 1, high: 0, medium: 0, low: 0, info: 0, total: 1 },
      findings: [
        {
          id: 'F-001',
          severity: 'Critical',
          title: 'missing signer',
          location: 'handler.rs',
          description: 'no signer',
          impact: 'drain',
          recommendation: 'require signer',
        },
      ],
    });
    const res = await request(app).get(`/api/audit/${taskId}/report.json`).expect(200);
    assert.equal(res.body.taskId, taskId);
    assert.equal(res.body.status, 'completed');
    assert.equal(res.body.findings.length, 1);
    assert.equal(res.body.email, undefined);
    assert.equal(res.body.paymentSignature, undefined);
  });
});

describe('POST /api/audit (batch / targets[])', () => {
  it('creates a batch with N tasks and taskIds array', async () => {
    const res = await request(app)
      .post('/api/audit')
      .send({
        targets: [
          { github: 'https://github.com/solana-labs/example-a' },
          { github: 'https://github.com/solana-labs/example-b' },
          {
            contractAddress: '4Nd1m6A8t3dV5Y5p7H5r2q6F9vJkL8m7n6W3u2X1Y4Z',
            moreInfo: 'This program upgraded last week.',
          },
        ],
        email: 'batch@example.com',
      })
      .expect(201);

    assert.ok(res.body.batchId);
    assert.ok(Array.isArray(res.body.taskIds));
    assert.equal(res.body.taskIds.length, 3);
    assert.equal(res.body.status, 'paid'); // FREE_AUDIT=true in .env.test
    assert.equal(res.body.freeAudit, true);
    assert.equal(res.body.amountSol, 0);

    await waitFor(
      () => res.body.taskIds.every((id: string) => fakeEngine.enqueued.includes(id)),
      1500,
    );
    for (const id of res.body.taskIds) {
      assert.ok(fakeEngine.enqueued.includes(id));
    }
  });

  it('rejects >5 targets', async () => {
    const targets = Array.from({ length: 6 }, (_, i) => ({
      github: `https://github.com/ex/proj-${i}`,
    }));
    const res = await request(app)
      .post('/api/audit')
      .send({ targets, email: 'u@example.com' })
      .expect(400);
    assert.equal(res.body.code, 'VALIDATION_ERROR');
  });

  it('rejects a target without any primary field (moreInfo-only)', async () => {
    const res = await request(app)
      .post('/api/audit')
      .send({
        targets: [{ moreInfo: 'just some text' }],
        email: 'u@example.com',
      })
      .expect(400);
    assert.equal(res.body.code, 'VALIDATION_ERROR');
  });

  it('rejects moreInfo > 2000 chars', async () => {
    // Multi-line so we hit the Zod max(2000) check rather than the
    // single-line OVERLONG_LINE heuristic guard at 500 chars.
    const overflow = Array.from({ length: 26 }, () => 'x'.repeat(80))
      .join('\n')
      .slice(0, 2001);
    const res = await request(app)
      .post('/api/audit')
      .send({
        targets: [
          {
            github: 'https://github.com/solana-labs/example',
            moreInfo: overflow,
          },
        ],
        email: 'u@example.com',
      })
      .expect(400);
    assert.equal(res.body.code, 'VALIDATION_ERROR');
  });
});

describe('GET /api/audit/batch/:batchId', () => {
  it('returns 404 for unknown batch', async () => {
    await request(app).get('/api/audit/batch/does-not-exist').expect(404);
  });

  it('aggregates batch + tasks with batchId linkage', async () => {
    const created = await request(app)
      .post('/api/audit')
      .send({
        targets: [
          { github: 'https://github.com/solana-labs/example-x' },
          { website: 'https://example.com' },
        ],
        email: 'agg@example.com',
      })
      .expect(201);

    const got = await request(app)
      .get(`/api/audit/batch/${created.body.batchId}`)
      .expect(200);

    assert.ok(got.body.batch);
    assert.equal(got.body.batch.batchId, created.body.batchId);
    assert.equal(got.body.batch.taskIds.length, 2);
    assert.equal(got.body.tasks.length, 2);
    for (const t of got.body.tasks) {
      assert.equal(t.batchId, created.body.batchId);
      // reportMarkdown must NOT leak for non-completed tasks
      if (t.status !== 'completed') {
        assert.equal(t.reportMarkdown, undefined);
      }
    }
  });
});
