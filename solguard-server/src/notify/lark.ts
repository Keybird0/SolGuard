// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// Operator-side three-stage lifecycle notifications via Lark / Feishu
// incoming webhook. All functions are fire-and-forget safe: if the webhook
// URL is unset, they return immediately; any transport error is logged at
// warn level but never thrown — audit business flow must not break because
// an operator channel is down.
//
// Reference: GoatGuard/agent-server/feishu-integration.ts (`notifyScanStarted`,
// `notifyScanCompleted`, `sendWebhookRichAlert`). The SolGuard port drops
// bitable / docx_builtin_import / im_v1 branches since we only speak via
// incoming webhook in this project.
import { config } from '../config';
import { logger } from '../logger';
import type { AuditTask } from '../types';

export type LarkStage = 'submitted' | 'paid' | 'completed' | 'failed';

type CardTemplate = 'green' | 'blue' | 'red' | 'orange' | 'grey';

interface LarkCardPayload {
  title: string;
  template: CardTemplate;
  markdown: string;
}

interface LarkRuntimeConfig {
  webhookUrl?: string;
  notifyStages: string[];
  envTag: string;
  solanaCluster: string;
  frontendUrl: string;
}

let configOverride: LarkRuntimeConfig | null = null;
let fetchOverride: typeof fetch | null = null;

/**
 * Override the config snapshot read by every notify function. Tests call
 * this with a custom shape so we don't have to mutate `process.env` or
 * re-import the global `config` module. Pass `null` to reset.
 */
export function setLarkConfigForTesting(cfg: LarkRuntimeConfig | null): void {
  configOverride = cfg;
}

/** Swap the `fetch` implementation. Used by tests to capture payloads. */
export function setLarkFetchForTesting(fn: typeof fetch | null): void {
  fetchOverride = fn;
}

function currentConfig(): LarkRuntimeConfig {
  if (configOverride) return configOverride;
  return {
    webhookUrl: config.larkWebhookUrl,
    notifyStages: config.larkNotifyStages,
    envTag: config.larkEnvTag,
    solanaCluster: config.solanaCluster,
    frontendUrl: config.frontendUrl,
  };
}

function stageEnabled(stage: LarkStage, cfg: LarkRuntimeConfig): boolean {
  if (!cfg.webhookUrl) return false;
  if (cfg.notifyStages.length === 0) return true;
  return cfg.notifyStages.includes(stage);
}

/**
 * POST an interactive card to the configured webhook. Non-2xx responses and
 * transport errors are logged but never re-thrown: notifications are
 * best-effort and must never block an audit in flight.
 */
async function postCard(payload: LarkCardPayload): Promise<void> {
  const cfg = currentConfig();
  if (!cfg.webhookUrl) return;
  const doFetch = fetchOverride ?? fetch;
  try {
    const resp = await doFetch(cfg.webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        msg_type: 'interactive',
        card: {
          header: {
            title: {
              tag: 'plain_text',
              content: `[${cfg.envTag}] ${payload.title}`,
            },
            template: payload.template,
          },
          elements: [{ tag: 'markdown', content: payload.markdown }],
        },
      }),
    });
    if (!resp.ok) {
      logger.warn(
        { status: resp.status, title: payload.title },
        'lark webhook non-2xx (ignored, business continues)',
      );
    }
  } catch (err) {
    logger.warn(
      { err, title: payload.title },
      'lark webhook failed (ignored, business continues)',
    );
  }
}

/**
 * Operator alert that is NOT tied to a lifecycle stage (e.g., email retry
 * exhausted). Always fires when the webhook URL is configured, regardless
 * of `LARK_NOTIFY_STAGES`.
 */
export async function postOperatorAlert(payload: LarkCardPayload): Promise<void> {
  await postCard(payload);
}

// ---- formatting helpers ----

function brief(inputs: AuditTask['inputs']): string {
  return inputs
    .map((inp, i) => {
      const truncated =
        inp.value.length > 80 ? `${inp.value.slice(0, 77)}...` : inp.value;
      return `  ${i + 1}. \`${inp.type}\` ${truncated}`;
    })
    .join('\n');
}

function stats(task: AuditTask): string {
  const s = task.statistics;
  if (!s) return 'N/A';
  return `${s.critical ?? 0}C / ${s.high ?? 0}H / ${s.medium ?? 0}M / ${s.low ?? 0}L / ${s.info ?? 0}I`;
}

function completedTemplate(task: AuditTask): CardTemplate {
  const s = task.statistics;
  if (!s) return 'green';
  if ((s.critical ?? 0) > 0) return 'red';
  if ((s.high ?? 0) > 0) return 'orange';
  return 'green';
}

function explorerLink(signature: string, cluster: string): string {
  const base = `https://explorer.solana.com/tx/${signature}`;
  return cluster === 'mainnet-beta' ? base : `${base}?cluster=${cluster}`;
}

function reportLink(task: AuditTask, cfg: LarkRuntimeConfig): string {
  return task.reportUrl ?? `${cfg.frontendUrl}/#report?taskId=${task.taskId}`;
}

function duration(task: AuditTask): string {
  if (!task.createdAt || !task.completedAt) return '—';
  const ms = Date.parse(task.completedAt) - Date.parse(task.createdAt);
  if (Number.isNaN(ms) || ms < 0) return '—';
  return `${(ms / 1000).toFixed(0)}s`;
}

// ---- stage entry points ----

/** Stage 1 · customer submitted the audit request (before payment). */
export async function notifyScanRequested(task: AuditTask): Promise<void> {
  const cfg = currentConfig();
  if (!stageEnabled('submitted', cfg)) return;
  const md =
    `**Task ID**: \`${task.taskId}\`\n` +
    `**Email**: ${task.email}\n` +
    `**Inputs** (${task.inputs.length}):\n${brief(task.inputs)}\n` +
    `**Amount**: ${task.paymentAmountSol ?? '-'} SOL → \`${task.paymentRecipient ?? '-'}\`\n` +
    `**Payment**: ${task.paymentUrl ? `[Phantom link](${task.paymentUrl})` : 'n/a (FREE_AUDIT?)'}`;
  await postCard({
    title: 'SolGuard audit request received · awaiting payment',
    template: 'green',
    markdown: md,
  });
}

/** Stage 2 · payment confirmed on-chain. */
export async function notifyPaymentConfirmed(task: AuditTask): Promise<void> {
  const cfg = currentConfig();
  if (!stageEnabled('paid', cfg)) return;
  const sig = task.paymentSignature ?? '—';
  const md =
    `**Task ID**: \`${task.taskId}\`\n` +
    `**Email**: ${task.email}\n` +
    `**Amount**: ${task.paymentAmountSol ?? '-'} SOL\n` +
    `**Signature**: \`${sig}\`\n` +
    `**Explorer**: [view tx](${explorerLink(sig, cfg.solanaCluster)})\n` +
    `Starting input normalization + AI audit agent (typically 5-8 min).`;
  await postCard({
    title: 'Payment confirmed · audit starting',
    template: 'blue',
    markdown: md,
  });
}

/** Stage 3a · audit finished successfully, report available. */
export async function notifyScanCompleted(task: AuditTask): Promise<void> {
  const cfg = currentConfig();
  if (!stageEnabled('completed', cfg)) return;
  const md =
    `**Task ID**: \`${task.taskId}\`\n` +
    `**Email**: ${task.email}\n` +
    `**Risk**: ${stats(task)}\n` +
    `**Report**: [open online](${reportLink(task, cfg)})\n` +
    `**Duration**: ${duration(task)} · customer email dispatched.`;
  await postCard({
    title: 'SolGuard scan completed',
    template: completedTemplate(task),
    markdown: md,
  });
}

/** Stage 3b · audit failed (agent crash, payment timeout, etc.). */
export async function notifyScanFailed(task: AuditTask): Promise<void> {
  const cfg = currentConfig();
  if (!stageEnabled('failed', cfg)) return;
  const md =
    `**Task ID**: \`${task.taskId}\`\n` +
    `**Email**: ${task.email}\n` +
    `**Status**: ${task.status}\n` +
    `**Error**: ${task.error ?? '(unknown)'}\n` +
    `Check \`data/logs/${task.taskId}.log\` or Railway logs for details.`;
  await postCard({
    title: 'SolGuard scan failed',
    template: 'red',
    markdown: md,
  });
}
