import 'dotenv/config';
import { z } from 'zod';

const configSchema = z.object({
  // Server
  port: z.coerce.number().int().positive().default(3000),
  nodeEnv: z.enum(['development', 'production', 'test']).default('development'),
  appVersion: z.string().default('0.1.0'),
  logLevel: z.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal']).default('info'),
  corsOrigins: z
    .string()
    .default('http://localhost:3000')
    .transform((s) => s.split(',').map((o) => o.trim()).filter(Boolean)),

  // LLM
  anthropicApiKey: z.string().optional(),
  openaiApiKey: z.string().optional(),
  llmProvider: z.enum(['anthropic', 'openai']).default('anthropic'),
  llmModel: z.string().default('claude-3-5-sonnet-20241022'),

  // Solana
  solanaCluster: z.enum(['devnet', 'testnet', 'mainnet-beta']).default('devnet'),
  solanaRpcUrl: z.string().url().default('https://api.devnet.solana.com'),
  solanaServiceWallet: z.string().optional(),
  auditPriceSol: z.coerce.number().positive().default(0.01),
  paymentTimeoutMs: z.coerce.number().int().positive().default(600_000),

  // Email
  smtpHost: z.string().optional(),
  smtpPort: z.coerce.number().int().positive().optional(),
  smtpSecure: z.coerce.boolean().default(false),
  smtpUser: z.string().optional(),
  smtpPass: z.string().optional(),
  emailFrom: z.string().default('SolGuard <noreply@solguard.xyz>'),

  // Agent
  ohCliPath: z.string().default('oh'),
  ohSkillDir: z.string().optional(),
  agentCallbackToken: z.string().default('change-me-to-random-string'),
  agentTimeoutMs: z.coerce.number().int().positive().default(600_000),

  // Storage
  dataDir: z.string().default('./data'),
  taskStore: z.enum(['in-memory', 'file-json']).default('in-memory'),
});

export type Config = z.infer<typeof configSchema>;

export const config: Config = configSchema.parse({
  port: process.env.PORT,
  nodeEnv: process.env.NODE_ENV,
  appVersion: process.env.APP_VERSION,
  logLevel: process.env.LOG_LEVEL,
  corsOrigins: process.env.CORS_ORIGINS,

  anthropicApiKey: process.env.ANTHROPIC_API_KEY,
  openaiApiKey: process.env.OPENAI_API_KEY,
  llmProvider: process.env.LLM_PROVIDER,
  llmModel: process.env.LLM_MODEL,

  solanaCluster: process.env.SOLANA_CLUSTER,
  solanaRpcUrl: process.env.SOLANA_RPC_URL,
  solanaServiceWallet: process.env.SOLANA_SERVICE_WALLET,
  auditPriceSol: process.env.AUDIT_PRICE_SOL,
  paymentTimeoutMs: process.env.PAYMENT_TIMEOUT_MS,

  smtpHost: process.env.SMTP_HOST,
  smtpPort: process.env.SMTP_PORT,
  smtpSecure: process.env.SMTP_SECURE,
  smtpUser: process.env.SMTP_USER,
  smtpPass: process.env.SMTP_PASS,
  emailFrom: process.env.EMAIL_FROM,

  ohCliPath: process.env.OH_CLI_PATH,
  ohSkillDir: process.env.OH_SKILL_DIR,
  agentCallbackToken: process.env.AGENT_CALLBACK_TOKEN,
  agentTimeoutMs: process.env.AGENT_TIMEOUT_MS,

  dataDir: process.env.DATA_DIR,
  taskStore: process.env.TASK_STORE,
});

export function hasAnyLlmKey(): boolean {
  return Boolean(config.anthropicApiKey || config.openaiApiKey);
}
