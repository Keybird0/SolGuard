import 'dotenv/config';
import { z } from 'zod';

const configSchema = z.object({
  port: z.coerce.number().int().positive().default(3000),
  nodeEnv: z.enum(['development', 'production', 'test']).default('development'),
  appVersion: z.string().default('0.1.0'),
  logLevel: z.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal']).default('info'),
  corsOrigins: z
    .string()
    .default('http://localhost:3000')
    .transform((s) =>
      s
        .split(',')
        .map((o) => o.trim())
        .filter(Boolean),
    ),
  publicBaseUrl: z.string().url().default('http://localhost:3000'),

  anthropicApiKey: z.string().optional(),
  openaiApiKey: z.string().optional(),
  llmProvider: z.enum(['anthropic', 'openai']).default('anthropic'),
  llmModel: z.string().default('claude-3-5-sonnet-20241022'),

  solanaCluster: z.enum(['devnet', 'testnet', 'mainnet-beta']).default('devnet'),
  solanaRpcUrl: z.string().url().default('https://api.devnet.solana.com'),
  solanaServiceWallet: z.string().optional(),
  auditPriceSol: z.coerce.number().positive().default(0.01),
  paymentTimeoutMs: z.coerce.number().int().positive().default(600_000),
  paymentPollIntervalMs: z.coerce.number().int().positive().default(5_000),
  freeAudit: z.coerce.boolean().default(false),

  smtpHost: z.string().optional(),
  smtpPort: z.coerce.number().int().positive().optional(),
  smtpSecure: z.coerce.boolean().default(false),
  smtpUser: z.string().optional(),
  smtpPass: z.string().optional(),
  emailFrom: z.string().default('SolGuard <noreply@solguard.xyz>'),
  emailReplyTo: z.string().optional(),
  emailBccOperator: z.string().optional(),
  frontendUrl: z.string().url().default('http://localhost:3000'),

  // Lark / Feishu incoming webhook — operator-side lifecycle notifications.
  // Leave URL empty to silence all three-stage cards (module degrades to a
  // no-op). `larkNotifyStages` is a CSV whitelist; empty array = send all.
  larkWebhookUrl: z.string().url().optional(),
  larkNotifyStages: z
    .string()
    .default('submitted,paid,completed,failed')
    .transform((s) =>
      s
        .split(',')
        .map((v) => v.trim())
        .filter(Boolean),
    ),
  larkEnvTag: z.string().default('local'),

  ohCliPath: z.string().default('oh'),
  ohSkillDir: z.string().optional(),
  ohOutputFormat: z.enum(['json-stream', 'json']).default('json-stream'),
  agentCallbackToken: z.string().default('change-me-to-random-string'),
  agentHmacRequired: z.coerce.boolean().default(false),
  agentTimeoutMs: z.coerce.number().int().positive().default(600_000),
  auditWorkdir: z.string().default('./data/workdir'),
  auditOutputRoot: z.string().default('./data/outputs'),

  runnerFallbackToPython: z.coerce.boolean().default(true),
  pythonBin: z.string().default('uv'),
  pythonRunAuditScript: z
    .string()
    .default('../skill/solana-security-audit-skill/scripts/run_audit.py'),

  gitBin: z.string().default('git'),
  inputNormalizerTimeoutMs: z.coerce.number().int().positive().default(120_000),

  rateLimitEnabled: z.coerce.boolean().default(false),
  rateLimitWindowMs: z.coerce.number().int().positive().default(60_000),
  rateLimitMaxRequests: z.coerce.number().int().positive().default(10),

  dataDir: z.string().default('./data'),
  taskStore: z.enum(['in-memory', 'file-json']).default('in-memory'),

  feedbackWebhookUrl: z.string().url().optional(),

  // Phase 6.4.2 · per-task audit log tail endpoint. Admin token is required
  // for /api/admin/logs/:taskId. Leave empty to disable the endpoint entirely.
  adminToken: z.string().default(''),
  taskLogDir: z.string().default('./data/logs'),
  taskLogMaxBytes: z.coerce.number().int().positive().default(2_000_000),
});

export type Config = z.infer<typeof configSchema>;

export const config: Config = configSchema.parse({
  port: process.env.PORT,
  nodeEnv: process.env.NODE_ENV,
  appVersion: process.env.APP_VERSION,
  logLevel: process.env.LOG_LEVEL,
  corsOrigins: process.env.CORS_ORIGINS,
  publicBaseUrl: process.env.PUBLIC_BASE_URL,

  anthropicApiKey: process.env.ANTHROPIC_API_KEY,
  openaiApiKey: process.env.OPENAI_API_KEY,
  llmProvider: process.env.LLM_PROVIDER,
  llmModel: process.env.LLM_MODEL,

  solanaCluster: process.env.SOLANA_CLUSTER,
  solanaRpcUrl: process.env.SOLANA_RPC_URL,
  solanaServiceWallet: process.env.SOLANA_SERVICE_WALLET,
  auditPriceSol: process.env.AUDIT_PRICE_SOL,
  paymentTimeoutMs: process.env.PAYMENT_TIMEOUT_MS,
  paymentPollIntervalMs: process.env.PAYMENT_POLL_INTERVAL_MS,
  freeAudit: process.env.FREE_AUDIT,

  smtpHost: process.env.SMTP_HOST,
  smtpPort: process.env.SMTP_PORT,
  smtpSecure: process.env.SMTP_SECURE,
  smtpUser: process.env.SMTP_USER,
  smtpPass: process.env.SMTP_PASS,
  emailFrom: process.env.EMAIL_FROM,
  emailReplyTo: process.env.EMAIL_REPLY_TO,
  emailBccOperator: process.env.EMAIL_BCC_OPERATOR,
  frontendUrl: process.env.FRONTEND_URL,

  larkWebhookUrl: process.env.LARK_WEBHOOK_URL,
  larkNotifyStages: process.env.LARK_NOTIFY_STAGES,
  larkEnvTag: process.env.LARK_ENV_TAG,

  ohCliPath: process.env.OH_CLI_PATH,
  ohSkillDir: process.env.OH_SKILL_DIR,
  ohOutputFormat: process.env.OH_OUTPUT_FORMAT,
  agentCallbackToken: process.env.AGENT_CALLBACK_TOKEN,
  agentHmacRequired: process.env.AGENT_HMAC_REQUIRED,
  agentTimeoutMs: process.env.AGENT_TIMEOUT_MS,
  auditWorkdir: process.env.AUDIT_WORKDIR,
  auditOutputRoot: process.env.AUDIT_OUTPUT_ROOT,

  runnerFallbackToPython: process.env.RUNNER_FALLBACK_TO_PYTHON,
  pythonBin: process.env.PYTHON_BIN,
  pythonRunAuditScript: process.env.PYTHON_RUN_AUDIT_SCRIPT,

  gitBin: process.env.GIT_BIN,
  inputNormalizerTimeoutMs: process.env.INPUT_NORMALIZER_TIMEOUT_MS,

  rateLimitEnabled: process.env.RATE_LIMIT_ENABLED,
  rateLimitWindowMs: process.env.RATE_LIMIT_WINDOW_MS,
  rateLimitMaxRequests: process.env.RATE_LIMIT_MAX_REQUESTS,

  dataDir: process.env.DATA_DIR,
  taskStore: process.env.TASK_STORE,

  feedbackWebhookUrl: process.env.FEEDBACK_WEBHOOK_URL,

  adminToken: process.env.ADMIN_TOKEN,
  taskLogDir: process.env.TASK_LOG_DIR,
  taskLogMaxBytes: process.env.TASK_LOG_MAX_BYTES,
});

export function hasAnyLlmKey(): boolean {
  return Boolean(config.anthropicApiKey || config.openaiApiKey);
}

export function isPaymentConfigured(): boolean {
  return Boolean(config.solanaServiceWallet);
}
