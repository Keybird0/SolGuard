// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// One-shot utility to validate SMTP credentials + the full email rendering
// pipeline without triggering a real audit. Usage (from solguard-server/):
//
//   npx tsx scripts/send-test-email.ts you@example.com
//
// Requires SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/EMAIL_FROM to be set
// (e.g., via `.env`). EMAIL_BCC_OPERATOR / EMAIL_REPLY_TO are honoured if
// present. Dumps a fake completed audit task through `enqueueAuditEmail`,
// so you'll get the full HTML + .md + .json attachments that a real
// customer would see.
import 'dotenv/config';
import { enqueueAuditEmail } from '../src/email';
import { logger } from '../src/logger';
import type { AuditTask } from '../src/types';

async function main(): Promise<void> {
  const recipient = process.argv[2];
  if (!recipient || !recipient.includes('@')) {
    console.error('Usage: tsx scripts/send-test-email.ts <recipient@example.com>');
    process.exit(2);
  }

  const now = new Date().toISOString();
  const fake: AuditTask = {
    taskId: `smtp-smoke-${Date.now()}`,
    inputs: [
      {
        type: 'github',
        value: 'https://github.com/coral-xyz/anchor',
      },
    ],
    email: recipient,
    status: 'completed',
    createdAt: now,
    updatedAt: now,
    completedAt: now,
    statistics: {
      critical: 1,
      high: 2,
      medium: 3,
      low: 4,
      info: 5,
      total: 15,
    },
    findings: [
      {
        id: 'F-001',
        severity: 'Critical',
        title: 'Missing signer check on privileged instruction',
        location: 'programs/demo/src/lib.rs:42',
        description:
          'The `admin_update` handler does not verify that the signer key equals the recorded admin.',
        impact: 'Anyone can call the instruction and modify protocol state.',
        recommendation:
          'Use `Signer<\'info>` or compare `ctx.accounts.admin.key()` against the stored admin pubkey.',
      },
      {
        id: 'F-002',
        severity: 'High',
        title: 'Unchecked arithmetic in reward calculation',
        location: 'programs/demo/src/rewards.rs:118',
        description: 'Multiplication can overflow on large balances.',
        impact: 'Silent overflow leads to incorrect reward payouts.',
        recommendation: 'Use `checked_mul` / `checked_add`.',
      },
    ],
    reportMarkdown:
      '# SolGuard test report\n\nThis is a smoke-test email. No real audit was performed.\n',
  };

  logger.info({ recipient, taskId: fake.taskId }, 'enqueueing fake audit email');
  await enqueueAuditEmail(fake);
  // `enqueueAuditEmail` is async but the actual send is fire-and-forget;
  // wait a short grace period so nodemailer can flush before exit.
  await new Promise((resolve) => setTimeout(resolve, 3_000));
  logger.info('done — check inbox (and spam folder)');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
