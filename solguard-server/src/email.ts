// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import nodemailer, { type Transporter } from 'nodemailer';
import type Mail from 'nodemailer/lib/mailer';
import { config } from './config';
import { logger } from './logger';
import { postOperatorAlert } from './notify/lark';
import type { AuditTask, Finding, Severity } from './types';

const RETRY_DELAYS_MS = [60_000, 5 * 60_000, 15 * 60_000];

export interface Mailer {
  sendMail(options: nodemailer.SendMailOptions): Promise<unknown>;
}

let transportSingleton: Transporter | null = null;
let testMailer: Mailer | null = null;

export function getMailer(): Mailer | null {
  if (testMailer) return testMailer;
  if (transportSingleton) return transportSingleton;
  if (!config.smtpHost || !config.smtpUser || !config.smtpPass) return null;

  transportSingleton = nodemailer.createTransport({
    host: config.smtpHost,
    port: config.smtpPort ?? 465,
    secure: config.smtpSecure,
    auth: { user: config.smtpUser, pass: config.smtpPass },
  });
  return transportSingleton;
}

export function setMailerForTesting(mailer: Mailer | null): void {
  testMailer = mailer;
  transportSingleton = null;
}

const SEVERITY_COLOR: Record<Severity, string> = {
  Critical: '#e74c3c',
  High: '#e67e22',
  Medium: '#f1c40f',
  Low: '#3498db',
  Info: '#95a5a6',
};

const SEVERITY_ORDER: Severity[] = ['Critical', 'High', 'Medium', 'Low', 'Info'];

const KNOWN_RULES: Array<{
  id: string;
  name: string;
  category: string;
  aliases?: string[];
}> = [
  {
    id: 'missing_signer_check',
    name: 'Missing Signer Check',
    category: 'Authorization',
    aliases: ['signer_check', 'missing_signer'],
  },
  {
    id: 'missing_owner_check',
    name: 'Missing Owner Check',
    category: 'Account Validation',
    aliases: ['owner_check', 'missing_owner'],
  },
  {
    id: 'account_data_matching',
    name: 'Account Data Matching',
    category: 'Account Validation',
    aliases: ['account_matching', 'data_matching'],
  },
  {
    id: 'type_cosplay',
    name: 'Type Cosplay / Discriminator',
    category: 'Account Validation',
    aliases: ['discriminator_check', 'type_confusion'],
  },
  {
    id: 'arbitrary_cpi',
    name: 'Arbitrary CPI',
    category: 'CPI Safety',
    aliases: ['arbitrary_cross_program_invocation', 'cpi_whitelist'],
  },
  {
    id: 'pda_derivation_error',
    name: 'PDA Derivation / Bump Seed',
    category: 'PDA Safety',
    aliases: ['pda_derivation', 'bump_seed', 'bump_seed_canonicalization'],
  },
  {
    id: 'pda_sharing',
    name: 'PDA Sharing / Seed Collision',
    category: 'PDA Safety',
    aliases: ['seed_collision'],
  },
  {
    id: 'duplicate_mutable_accounts',
    name: 'Duplicate Mutable Accounts',
    category: 'Account Validation',
    aliases: ['duplicate_accounts'],
  },
  {
    id: 'closing_account_error',
    name: 'Closing Account Error',
    category: 'Lifecycle',
    aliases: ['closing_account', 'unsafe_close'],
  },
  {
    id: 'sysvar_spoofing',
    name: 'Sysvar Address Check',
    category: 'Account Validation',
    aliases: ['sysvar_check', 'sysvar_address_checking'],
  },
  {
    id: 'uninitialized_account',
    name: 'Uninitialized Account',
    category: 'Lifecycle',
    aliases: ['init_check'],
  },
  {
    id: 'reinit_attack',
    name: 'Re-init Attack',
    category: 'Lifecycle',
    aliases: ['reinitialization'],
  },
  {
    id: 'integer_overflow',
    name: 'Integer Overflow / Underflow',
    category: 'Arithmetic',
    aliases: ['arithmetic_overflow', 'unchecked_math'],
  },
  {
    id: 'semgrep_assets',
    name: 'Semgrep Solana Rules',
    category: 'Pattern Scanners',
    aliases: ['semgrep', 'solana_manual_accountinfo_deserialize'],
  },
];

const CATEGORY_ORDER = [
  'Authorization',
  'Account Validation',
  'CPI Safety',
  'PDA Safety',
  'Lifecycle',
  'Arithmetic',
  'Pattern Scanners',
  'Additional Checks',
];

function sortBySeverity(findings: Finding[]): Finding[] {
  return [...findings].sort(
    (a, b) =>
      SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity) ||
      a.location.localeCompare(b.location),
  );
}

function renderTopFindings(findings: Finding[]): string {
  const top = sortBySeverity(findings).slice(0, 3);
  if (top.length === 0) return '<p>No findings reported.</p>';
  const rows = top
    .map(
      (f) => `
    <tr>
      <td style="padding:8px;border-bottom:1px solid #eee;vertical-align:top">
        <span style="display:inline-block;padding:2px 8px;border-radius:4px;background:${SEVERITY_COLOR[f.severity]};color:#fff;font-size:12px">${f.severity}</span>
      </td>
      <td style="padding:8px;border-bottom:1px solid #eee">
        <strong>${escapeHtml(f.title)}</strong><br/>
        <span style="color:#666;font-size:12px">${escapeHtml(f.location)}</span>
      </td>
    </tr>`,
    )
    .join('');
  return `<table style="width:100%;border-collapse:collapse;margin-top:12px">${rows}</table>`;
}

function escapeHtml(input: string): string {
  return input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function normalizeRuleId(ruleId: string | undefined): string {
  return String(ruleId ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function matchKnownRule(ruleId: string | undefined): (typeof KNOWN_RULES)[number] | null {
  const norm = normalizeRuleId(ruleId);
  if (!norm) return null;
  for (const rule of KNOWN_RULES) {
    if (norm === rule.id) return rule;
  }
  for (const rule of KNOWN_RULES) {
    if (norm.startsWith(rule.id + '_') || norm.endsWith('_' + rule.id)) {
      return rule;
    }
  }
  for (const rule of KNOWN_RULES) {
    if (
      rule.aliases?.some(
        (alias) =>
          norm === alias ||
          norm.startsWith(alias + '_') ||
          norm.endsWith('_' + alias),
      )
    ) {
      return rule;
    }
  }
  return null;
}

function ratingFromStats(task: AuditTask): string {
  const stats = task.statistics;
  if (!stats) return 'U';
  if ((stats.critical ?? 0) > 0) return 'D';
  if ((stats.high ?? 0) > 0) return 'C';
  if ((stats.medium ?? 0) > 2) return 'C';
  if ((stats.medium ?? 0) > 0) return 'B';
  if ((stats.low ?? 0) > 0) return 'A';
  return 'S';
}

function totalFindings(task: AuditTask): number {
  return (
    task.findings?.length ??
    task.statistics?.total ??
    ((task.statistics?.critical ?? 0) +
      (task.statistics?.high ?? 0) +
      (task.statistics?.medium ?? 0) +
      (task.statistics?.low ?? 0) +
      (task.statistics?.info ?? 0))
  );
}

function targetName(task: AuditTask): string {
  return task.inputs[0]?.value ?? task.taskId;
}

function buildRiskSummaryMarkdown(task: AuditTask): string {
  const stats = task.statistics;
  const findings = sortBySeverity(task.findings ?? []);
  const top = findings.slice(0, 5);
  const lines: string[] = [
    '# Risk Summary',
    '',
    `- Audit target: ${targetName(task)}`,
    `- Overall rating: ${ratingFromStats(task)}`,
    `- Completed: ${task.completedAt ?? '—'}`,
    `- Total findings: ${totalFindings(task)}`,
    '',
    '## At-a-glance',
    '',
    '| Severity | Count |',
    '| --- | ---: |',
  ];

  for (const severity of SEVERITY_ORDER) {
    const key = severity.toLowerCase() as keyof NonNullable<AuditTask['statistics']>;
    lines.push(`| ${severity} | ${stats?.[key] ?? 0} |`);
  }
  lines.push(`| Total | ${totalFindings(task)} |`, '');

  lines.push('## Top risks');
  lines.push('');
  if (top.length === 0) {
    lines.push('_No findings recorded._', '');
  } else {
    top.forEach((finding, index) => {
      const oneLine = (finding.description || finding.impact || '')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 220);
      lines.push(
        `${index + 1}. [${finding.severity}] ${finding.title} — \`${finding.location}\``,
      );
      if (oneLine) lines.push(`   ${oneLine}${oneLine.length >= 220 ? '...' : ''}`);
      lines.push('');
    });
  }

  lines.push('## What this means');
  lines.push('');
  if ((stats?.critical ?? 0) > 0) {
    lines.push('- Critical findings require immediate remediation before production use.');
  }
  if ((stats?.high ?? 0) > 0) {
    lines.push('- High findings can bypass authorization or account validation assumptions.');
  }
  if ((stats?.medium ?? 0) > 0) {
    lines.push('- Medium findings should be scheduled for remediation and regression tests.');
  }
  if (totalFindings(task) === 0) {
    lines.push('- No findings were raised by the audit pipeline.');
  }
  lines.push('');
  lines.push(
    'Open the Full Assessment for detailed evidence and remediation. Open the Checklist Result for coverage proof.',
  );
  return lines.join('\n');
}

function buildFullAssessmentMarkdown(task: AuditTask): string {
  const findings = sortBySeverity(task.findings ?? []);
  const stats = task.statistics;
  const lines: string[] = [
    '# Full Assessment',
    '',
    `- Audit target: ${targetName(task)}`,
    `- Overall rating: ${ratingFromStats(task)}`,
    `- Completed: ${task.completedAt ?? '—'}`,
    `- Breakdown: ${stats?.critical ?? 0} critical · ${stats?.high ?? 0} high · ${stats?.medium ?? 0} medium · ${stats?.low ?? 0} low · ${stats?.info ?? 0} info`,
    `- Total findings: ${totalFindings(task)}`,
    '',
    '## Findings',
    '',
  ];

  if (findings.length === 0) {
    lines.push('_No findings recorded for this target._');
    return lines.join('\n');
  }

  findings.forEach((finding, index) => {
    lines.push(`### ${index + 1}. [${finding.severity}] ${finding.title}`);
    lines.push('');
    lines.push(`- Rule: \`${finding.ruleId ?? finding.id}\``);
    lines.push(`- Location: \`${finding.location}\``);
    if (typeof finding.confidence === 'number') {
      lines.push(`- Confidence: ${finding.confidence.toFixed(2)}`);
    }
    lines.push('');
    lines.push('**Description.**');
    lines.push('');
    lines.push(finding.description || 'No description provided.');
    lines.push('');
    if (finding.impact && finding.impact !== finding.description) {
      lines.push('**Impact.**');
      lines.push('');
      lines.push(finding.impact);
      lines.push('');
    }
    lines.push('**Recommendation.**');
    lines.push('');
    lines.push(finding.recommendation || 'No recommendation provided.');
    lines.push('');
    if (finding.codeSnippet) {
      lines.push('**Code.**');
      lines.push('');
      lines.push('```rust');
      lines.push(finding.codeSnippet);
      lines.push('```');
      lines.push('');
    }
    lines.push('---', '');
  });

  return lines.join('\n');
}

function buildChecklistMarkdown(task: AuditTask): string {
  const bucket = new Map<
    string,
    {
      rule: { id: string; name: string; category: string };
      matches: Array<{ severity: Severity; title: string; location: string }>;
    }
  >();

  for (const rule of KNOWN_RULES) {
    bucket.set(`known:${rule.id}`, { rule, matches: [] });
  }

  for (const finding of task.findings ?? []) {
    const known = matchKnownRule(finding.ruleId ?? finding.id);
    if (known) {
      bucket.get(`known:${known.id}`)?.matches.push({
        severity: finding.severity,
        title: finding.title,
        location: finding.location,
      });
      continue;
    }
    const normalized = normalizeRuleId(finding.ruleId ?? finding.id) || finding.id;
    const key = `extra:${normalized}`;
    if (!bucket.has(key)) {
      bucket.set(key, {
        rule: {
          id: normalized,
          name: finding.title,
          category: 'Additional Checks',
        },
        matches: [],
      });
    }
    bucket.get(key)?.matches.push({
      severity: finding.severity,
      title: finding.title,
      location: finding.location,
    });
  }

  const byCategory = new Map<string, Array<(typeof bucket extends Map<string, infer V> ? V : never)>>();
  for (const entry of bucket.values()) {
    const category = entry.rule.category;
    byCategory.set(category, [...(byCategory.get(category) ?? []), entry]);
  }

  const totalRules = bucket.size;
  const hitRules = [...bucket.values()].filter((entry) => entry.matches.length > 0).length;
  const lines: string[] = [
    '# Checklist Result',
    '',
    `- Audit target: ${targetName(task)}`,
    `- Completed: ${task.completedAt ?? '—'}`,
    `- Coverage: ${totalRules} rule classes checked · ${hitRules} with findings · ${totalRules - hitRules} clean`,
    `- Matched findings: ${task.findings?.length ?? 0}`,
    '',
    'Legend: finding detected / clean — no match.',
    '',
  ];

  const categories = [
    ...CATEGORY_ORDER.filter((category) => byCategory.has(category)),
    ...[...byCategory.keys()].filter((category) => !CATEGORY_ORDER.includes(category)),
  ];

  for (const category of categories) {
    const entries = byCategory.get(category) ?? [];
    if (entries.length === 0) continue;
    entries.sort((a, b) => b.matches.length - a.matches.length || a.rule.name.localeCompare(b.rule.name));
    lines.push(`## ${category}`, '');
    for (const entry of entries) {
      const label =
        entry.matches.length > 0
          ? `${entry.matches.length} finding${entry.matches.length === 1 ? '' : 's'}`
          : 'clean — no match';
      lines.push(`- ${entry.rule.name} (\`${entry.rule.id}\`) — ${label}`);
      for (const match of sortBySeverity(
        entry.matches.map((item, index) => ({
          id: `${entry.rule.id}-${index}`,
          ruleId: entry.rule.id,
          severity: item.severity,
          title: item.title,
          location: item.location,
          description: '',
          impact: '',
          recommendation: '',
        })),
      )) {
        lines.push(`  - [${match.severity}] ${match.title} @ \`${match.location}\``);
      }
    }
    lines.push('');
  }

  lines.push(
    `Coverage summary: ${totalRules} canonical rule classes were evaluated; ${hitRules} triggered and ${totalRules - hitRules} came back clean.`,
  );
  return lines.join('\n');
}

/**
 * Public report URL for a task. Prefers `task.reportUrl` (agent-supplied),
 * otherwise falls back to the Phase-4 frontend hash route so the link
 * resolves even when we only host the SPA at `PUBLIC_BASE_URL`.
 */
function publicReportUrl(task: AuditTask): string {
  const id = task.batchId ?? task.taskId;
  return (
    task.reportUrl ?? `${config.publicBaseUrl}/#report/${encodeURIComponent(id)}`
  );
}

function publicFeedbackUrl(task: AuditTask): string {
  return `${config.publicBaseUrl}/#feedback/${encodeURIComponent(task.taskId)}`;
}

function renderCompletedEmail(task: AuditTask): {
  subject: string;
  html: string;
  text: string;
} {
  const findings = task.findings ?? [];
  const stats = task.statistics;
  const riskBadge = stats
    ? `${stats.critical ?? 0}C / ${stats.high ?? 0}H / ${stats.medium ?? 0}M / ${stats.low ?? 0}L`
    : 'N/A';
  const reportUrl = publicReportUrl(task);
  const feedbackUrl = publicFeedbackUrl(task);
  const projectName = task.inputs[0]?.value ?? task.taskId;
  const subject = `SolGuard Audit Complete — ${projectName}`;

  const html = `
<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:640px;margin:0 auto;padding:24px;color:#1a1a1a">
  <h1 style="color:#7c5cff;margin:0 0 8px">SolGuard Audit Report</h1>
  <p style="color:#666;margin:0 0 24px">Task <code>${task.taskId}</code></p>

  <table style="width:100%;border-collapse:collapse;margin:8px 0 16px">
    <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#666">Status</td>
        <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold">${task.status}</td></tr>
    <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#666">Findings</td>
        <td style="padding:8px;border-bottom:1px solid #eee">${riskBadge}</td></tr>
    <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#666">Completed</td>
        <td style="padding:8px;border-bottom:1px solid #eee">${task.completedAt ?? '—'}</td></tr>
  </table>

  <h2 style="margin:24px 0 8px;font-size:18px">Top findings</h2>
  ${renderTopFindings(findings)}

  <div style="margin:32px 0">
    <a href="${reportUrl}" style="display:inline-block;padding:12px 20px;background:#7c5cff;color:#fff;text-decoration:none;border-radius:6px">View full report</a>
    <a href="${feedbackUrl}" style="display:inline-block;margin-left:12px;padding:12px 20px;color:#7c5cff;text-decoration:none;border:1px solid #7c5cff;border-radius:6px">Share feedback</a>
  </div>

  <p style="color:#999;font-size:12px;margin-top:32px">Three Markdown attachments are included: Risk Summary, Full Assessment, and Checklist Result.</p>
  <p style="color:#999;font-size:12px;margin-top:4px">— SolGuard · Solana security audit agent</p>
</div>`.trim();

  const text =
    `SolGuard Audit Report\n` +
    `Task: ${task.taskId}\n` +
    `Status: ${task.status}\n` +
    `Findings: ${riskBadge}\n` +
    `Full report: ${reportUrl}\n` +
    `Feedback: ${feedbackUrl}\n\n` +
    `Attachments: solguard-${task.taskId}-risk-summary.md, solguard-${task.taskId}-full-assessment.md, solguard-${task.taskId}-checklist-result.md\n`;

  return { subject, html, text };
}

function renderFailedEmail(task: AuditTask): {
  subject: string;
  html: string;
  text: string;
} {
  const reason = task.error ?? 'Unknown error';
  const subject = `SolGuard Audit Failed — ${task.taskId}`;
  const feedbackUrl = publicFeedbackUrl(task);

  const html = `
<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:640px;margin:0 auto;padding:24px;color:#1a1a1a">
  <h1 style="color:#e74c3c;margin:0 0 8px">SolGuard Audit Could Not Complete</h1>
  <p style="color:#666;margin:0 0 24px">Task <code>${task.taskId}</code></p>

  <p style="margin:0 0 12px">We were unable to finish scanning your submission. Our team has been notified and will look into it.</p>

  <table style="width:100%;border-collapse:collapse;margin:8px 0 16px">
    <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#666">Status</td>
        <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold">${task.status}</td></tr>
    <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#666">Reason</td>
        <td style="padding:8px;border-bottom:1px solid #eee;color:#e74c3c">${escapeHtml(reason)}</td></tr>
    <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#666">Updated</td>
        <td style="padding:8px;border-bottom:1px solid #eee">${task.completedAt ?? task.updatedAt ?? '—'}</td></tr>
  </table>

  <p style="margin:16px 0">If you paid on-chain, the transaction has already been recorded — please <b>reply to this email</b> with your task ID and we'll either refund or rerun the audit manually.</p>

  <div style="margin:24px 0">
    <a href="${feedbackUrl}" style="display:inline-block;padding:10px 16px;color:#7c5cff;text-decoration:none;border:1px solid #7c5cff;border-radius:6px">Report this issue</a>
  </div>

  <p style="color:#999;font-size:12px;margin-top:32px">— SolGuard · Solana security audit agent</p>
</div>`.trim();

  const text =
    `SolGuard Audit Could Not Complete\n` +
    `Task: ${task.taskId}\n` +
    `Status: ${task.status}\n` +
    `Reason: ${reason}\n\n` +
    `Reply to this email with your task ID for manual follow-up.\n` +
    `Report issue: ${feedbackUrl}\n`;

  return { subject, html, text };
}

export function renderAuditEmail(task: AuditTask): {
  subject: string;
  html: string;
  text: string;
} {
  return task.status === 'failed'
    ? renderFailedEmail(task)
    : renderCompletedEmail(task);
}

interface QueuedMail {
  task: AuditTask;
  attempts: number;
  lastError?: string;
}

const queue = new Map<string, QueuedMail>();

export async function enqueueAuditEmail(task: AuditTask): Promise<void> {
  if (task.status !== 'completed' && task.status !== 'failed') return;
  const entry: QueuedMail = queue.get(task.taskId) ?? { task, attempts: 0 };
  entry.task = task;
  queue.set(task.taskId, entry);
  await processEntry(entry);
}

function buildAttachments(task: AuditTask): Mail.Attachment[] {
  const out: Mail.Attachment[] = [];
  if (task.status === 'completed') {
    out.push(
      {
        filename: `solguard-${task.taskId}-risk-summary.md`,
        content: Buffer.from(buildRiskSummaryMarkdown(task), 'utf8'),
        contentType: 'text/markdown',
      },
      {
        filename: `solguard-${task.taskId}-full-assessment.md`,
        content: Buffer.from(buildFullAssessmentMarkdown(task), 'utf8'),
        contentType: 'text/markdown',
      },
      {
        filename: `solguard-${task.taskId}-checklist-result.md`,
        content: Buffer.from(buildChecklistMarkdown(task), 'utf8'),
        contentType: 'text/markdown',
      },
    );
  }
  return out;
}

/**
 * Non-empty BCC list, excluding the customer's own address so an operator
 * who is also the recipient doesn't get duplicated.
 */
function buildBcc(task: AuditTask): string[] | undefined {
  if (!config.emailBccOperator) return undefined;
  const bcc = [config.emailBccOperator].filter(
    (addr) => addr && addr !== task.email,
  );
  return bcc.length > 0 ? bcc : undefined;
}

async function processEntry(entry: QueuedMail): Promise<void> {
  const mailer = getMailer();
  const { task } = entry;
  const { subject, html, text } = renderAuditEmail(task);
  const attachments = buildAttachments(task);
  const bcc = buildBcc(task);
  const replyTo = config.emailReplyTo || undefined;

  if (!mailer) {
    logger.info(
      { to: task.email, subject, attachments: attachments.length, bcc },
      '[email] SMTP not configured, logging only',
    );
    queue.delete(task.taskId);
    return;
  }

  try {
    await mailer.sendMail({
      from: config.emailFrom,
      replyTo,
      to: task.email,
      bcc,
      subject,
      text,
      html,
      attachments,
    });
    logger.info(
      { taskId: task.taskId, to: task.email, bcc, attachments: attachments.length },
      'audit email sent',
    );
    queue.delete(task.taskId);
  } catch (err) {
    entry.attempts += 1;
    entry.lastError = err instanceof Error ? err.message : String(err);
    logger.warn(
      { err: entry.lastError, taskId: task.taskId, attempts: entry.attempts },
      'sendMail failed',
    );
    if (entry.attempts >= RETRY_DELAYS_MS.length) {
      logger.error(
        { taskId: task.taskId, lastError: entry.lastError },
        'email giving up after max retries',
      );
      // Operator alert bypasses LARK_NOTIFY_STAGES — this is an ops
      // issue that needs manual follow-up (resend / investigate SMTP).
      void postOperatorAlert({
        title: 'SolGuard email delivery failed',
        template: 'red',
        markdown:
          `**Task**: \`${task.taskId}\`\n` +
          `**Customer**: ${task.email}\n` +
          `**Error**: ${entry.lastError}\n` +
          `Please resend manually or check SMTP credentials.`,
      }).catch(() => {
        /* best-effort, already logged */
      });
      queue.delete(task.taskId);
      return;
    }
    const delay = RETRY_DELAYS_MS[entry.attempts - 1] ?? 60_000;
    setTimeout(() => {
      void processEntry(entry);
    }, delay).unref?.();
  }
}

export function getEmailQueueSizeForTesting(): number {
  return queue.size;
}
