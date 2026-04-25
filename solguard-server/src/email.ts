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

function sortBySeverity(findings: Finding[]): Finding[] {
  const order: Record<Severity, number> = {
    Critical: 0,
    High: 1,
    Medium: 2,
    Low: 3,
    Info: 4,
  };
  return [...findings].sort((a, b) => order[a.severity] - order[b.severity]);
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

/**
 * Public report URL for a task. Prefers `task.reportUrl` (agent-supplied),
 * otherwise falls back to the Phase-4 frontend hash route so the link
 * resolves even when we only host the SPA at `PUBLIC_BASE_URL`.
 */
function publicReportUrl(task: AuditTask): string {
  return (
    task.reportUrl ?? `${config.publicBaseUrl}/#report?taskId=${task.taskId}`
  );
}

function publicFeedbackUrl(task: AuditTask): string {
  return `${config.publicBaseUrl}/#feedback?taskId=${task.taskId}`;
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

  <p style="color:#999;font-size:12px;margin-top:32px">Two attachments are included: the Markdown report and a JSON summary with all findings + metadata.</p>
  <p style="color:#999;font-size:12px;margin-top:4px">— SolGuard · Solana security audit agent</p>
</div>`.trim();

  const text =
    `SolGuard Audit Report\n` +
    `Task: ${task.taskId}\n` +
    `Status: ${task.status}\n` +
    `Findings: ${riskBadge}\n` +
    `Full report: ${reportUrl}\n` +
    `Feedback: ${feedbackUrl}\n\n` +
    `Attachments: solguard-${task.taskId}.md, solguard-${task.taskId}.json\n`;

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
  if (task.reportMarkdown) {
    out.push({
      filename: `solguard-${task.taskId}.md`,
      content: Buffer.from(task.reportMarkdown, 'utf8'),
      contentType: 'text/markdown',
    });
  }
  if (task.status === 'completed') {
    const json = {
      taskId: task.taskId,
      status: task.status,
      statistics: task.statistics,
      findings: task.findings ?? [],
      reportUrl: publicReportUrl(task),
      completedAt: task.completedAt,
      inputs: task.inputs,
    };
    out.push({
      filename: `solguard-${task.taskId}.json`,
      content: Buffer.from(JSON.stringify(json, null, 2), 'utf8'),
      contentType: 'application/json',
    });
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
