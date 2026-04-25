// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { afterEach, describe, it } from 'node:test';
import {
  notifyPaymentConfirmed,
  notifyScanCompleted,
  notifyScanFailed,
  notifyScanRequested,
  postOperatorAlert,
  setLarkConfigForTesting,
  setLarkFetchForTesting,
  type LarkStage,
} from './lark';
import type { AuditTask } from '../types';

interface Capture {
  url: string;
  body: Record<string, unknown>;
}

function makeFetch(
  captures: Capture[],
  resp: { ok: boolean; status: number } = { ok: true, status: 200 },
  throwErr?: Error,
): typeof fetch {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    if (throwErr) throw throwErr;
    const url = typeof input === 'string' ? input : String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    captures.push({ url, body });
    return { ok: resp.ok, status: resp.status } as Response;
  }) as typeof fetch;
}

const DEFAULT_URL = 'https://example.com/hook';

function configure(
  stages: LarkStage[] | 'all',
  url: string | null = DEFAULT_URL,
): void {
  setLarkConfigForTesting({
    webhookUrl: url === null ? undefined : url,
    notifyStages: stages === 'all' ? [] : (stages as string[]),
    envTag: 'test',
    solanaCluster: 'devnet',
    frontendUrl: 'http://localhost:3000',
  });
}

function sampleTask(overrides: Partial<AuditTask> = {}): AuditTask {
  const now = new Date().toISOString();
  return {
    taskId: 't-1',
    inputs: [{ type: 'github', value: 'https://github.com/a/b' }],
    email: 'u@example.com',
    status: 'paying',
    createdAt: now,
    updatedAt: now,
    paymentAmountSol: 0.001,
    paymentRecipient: 'DYmzG1oSfzJoVTSXedpn1mz3MqeH7H6ykV5RBsZJuD8i',
    paymentUrl: 'solana:...',
    ...overrides,
  };
}

afterEach(() => {
  setLarkConfigForTesting(null);
  setLarkFetchForTesting(null);
});

describe('notify/lark', () => {
  it('skips fetch entirely when webhook URL is not configured', async () => {
    const captures: Capture[] = [];
    configure('all', null);
    setLarkFetchForTesting(makeFetch(captures));
    await notifyScanRequested(sampleTask());
    await notifyPaymentConfirmed(sampleTask({ paymentSignature: 'sig1' }));
    await notifyScanCompleted(sampleTask({ status: 'completed' }));
    await notifyScanFailed(sampleTask({ status: 'failed', error: 'boom' }));
    assert.equal(captures.length, 0);
  });

  it('emits an interactive card with envTag-prefixed title', async () => {
    const captures: Capture[] = [];
    configure('all');
    setLarkFetchForTesting(makeFetch(captures));
    await notifyScanRequested(sampleTask());
    assert.equal(captures.length, 1);
    const body = captures[0]?.body as {
      msg_type: string;
      card: { header: { title: { content: string } }; elements: unknown[] };
    };
    assert.equal(body.msg_type, 'interactive');
    assert.ok(body.card.header.title.content.startsWith('[test] '));
    assert.ok(Array.isArray(body.card.elements));
  });

  it('honours the LARK_NOTIFY_STAGES whitelist', async () => {
    const captures: Capture[] = [];
    configure(['paid']);
    setLarkFetchForTesting(makeFetch(captures));
    await notifyScanRequested(sampleTask());
    await notifyPaymentConfirmed(sampleTask({ paymentSignature: 'sig1' }));
    await notifyScanCompleted(sampleTask({ status: 'completed' }));
    await notifyScanFailed(sampleTask({ status: 'failed', error: 'x' }));
    assert.equal(captures.length, 1, 'only "paid" stage should be emitted');
    const headerTitle = (
      captures[0]?.body as {
        card: { header: { title: { content: string } } };
      }
    ).card.header.title.content;
    assert.ok(headerTitle.includes('Payment confirmed'));
  });

  it('non-2xx response is swallowed (business must continue)', async () => {
    const captures: Capture[] = [];
    configure('all');
    setLarkFetchForTesting(makeFetch(captures, { ok: false, status: 500 }));
    await assert.doesNotReject(notifyScanRequested(sampleTask()));
    assert.equal(captures.length, 1);
  });

  it('fetch throwing is swallowed (business must continue)', async () => {
    configure('all');
    setLarkFetchForTesting(makeFetch([], { ok: true, status: 200 }, new Error('dns fail')));
    await assert.doesNotReject(notifyScanRequested(sampleTask()));
  });

  it('completed template reflects severity: critical→red, high→orange, else→green', async () => {
    const captures: Capture[] = [];
    configure('all');
    setLarkFetchForTesting(makeFetch(captures));

    await notifyScanCompleted(
      sampleTask({
        status: 'completed',
        statistics: { critical: 1, high: 0, medium: 0, low: 0, info: 0, total: 1 },
      }),
    );
    await notifyScanCompleted(
      sampleTask({
        status: 'completed',
        statistics: { critical: 0, high: 2, medium: 0, low: 0, info: 0, total: 2 },
      }),
    );
    await notifyScanCompleted(
      sampleTask({
        status: 'completed',
        statistics: { critical: 0, high: 0, medium: 3, low: 1, info: 0, total: 4 },
      }),
    );

    const templates = captures.map(
      (c) =>
        (c.body as { card: { header: { template: string } } }).card.header
          .template,
    );
    assert.deepEqual(templates, ['red', 'orange', 'green']);
  });

  it('postOperatorAlert bypasses the stage whitelist', async () => {
    const captures: Capture[] = [];
    configure([]); // empty whitelist in this project means send all;
    // simulate a "silent stage" setup explicitly:
    setLarkConfigForTesting({
      webhookUrl: 'https://example.com/hook',
      notifyStages: ['submitted'], // completed/failed suppressed
      envTag: 'test',
      solanaCluster: 'devnet',
      frontendUrl: 'http://localhost:3000',
    });
    setLarkFetchForTesting(makeFetch(captures));
    await notifyScanFailed(sampleTask({ status: 'failed', error: 'x' }));
    assert.equal(captures.length, 0, 'stage-gated notify is suppressed');
    await postOperatorAlert({
      title: 'Email retry exhausted',
      template: 'red',
      markdown: 'needs manual follow-up',
    });
    assert.equal(captures.length, 1, 'operator alert bypasses whitelist');
  });
});
