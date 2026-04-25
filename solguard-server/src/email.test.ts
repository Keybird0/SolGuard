// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { after, describe, it } from 'node:test';
import { renderAuditEmail, setMailerForTesting, enqueueAuditEmail } from './email';
import type { AuditTask } from './types';

function sampleCompleted(): AuditTask {
  const now = new Date().toISOString();
  return {
    taskId: 'e1',
    inputs: [{ type: 'github', value: 'https://github.com/a/b' }],
    email: 'u@example.com',
    status: 'completed',
    createdAt: now,
    updatedAt: now,
    completedAt: now,
    findings: [
      {
        id: 'F-001',
        severity: 'Critical',
        title: 'Missing signer check',
        location: 'programs/x/src/lib.rs:42',
        description: '...',
        impact: '...',
        recommendation: '...',
      },
    ],
    statistics: { critical: 1, high: 0, medium: 0, low: 0, info: 0, total: 1 },
    reportMarkdown: '# SolGuard report',
  };
}

after(() => setMailerForTesting(null));

describe('email rendering', () => {
  it('produces subject, html, text with severity badge', () => {
    const { subject, html, text } = renderAuditEmail(sampleCompleted());
    assert.ok(subject.includes('Complete'));
    assert.ok(html.includes('Critical'));
    assert.ok(html.includes('Missing signer check'));
    assert.ok(text.includes('1C / 0H'));
  });

  it('sendMail is called via mailer stub with three report attachments', async () => {
    const calls: { to?: string; subject?: string; attachments?: unknown[] }[] = [];
    setMailerForTesting({
      sendMail: async (opts) => {
        calls.push({
          to: String(opts.to),
          subject: opts.subject,
          attachments: opts.attachments as unknown[],
        });
        return { ok: true };
      },
    });
    await enqueueAuditEmail(sampleCompleted());
    assert.equal(calls.length, 1);
    assert.equal(calls[0]?.to, 'u@example.com');
    const attachments = calls[0]?.attachments as
      | Array<{ filename?: string; content?: Buffer }>
      | undefined;
    assert.equal(attachments?.length, 3);
    assert.deepEqual(
      attachments?.map((item) => item.filename),
      [
        'solguard-e1-risk-summary.md',
        'solguard-e1-full-assessment.md',
        'solguard-e1-checklist-result.md',
      ],
    );
    assert.match(String(attachments?.[0]?.content), /Risk Summary/);
    assert.match(String(attachments?.[1]?.content), /Full Assessment/);
    assert.match(String(attachments?.[2]?.content), /Checklist Result/);
  });
});
