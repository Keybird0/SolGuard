import { z } from 'zod';

const SOLANA_ADDRESS_REGEX = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
const GITHUB_URL_REGEX = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/;

export const auditInputSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('github'),
    value: z
      .string()
      .url()
      .regex(GITHUB_URL_REGEX, 'Must be a valid GitHub repo URL (https://github.com/owner/repo)'),
  }),
  z.object({
    type: z.literal('contract_address'),
    value: z.string().regex(SOLANA_ADDRESS_REGEX, 'Invalid Solana program address'),
  }),
  z.object({
    type: z.literal('whitepaper'),
    value: z.string().url(),
  }),
  z.object({
    type: z.literal('website'),
    value: z.string().url(),
  }),
]);

export const createAuditSchema = z.object({
  inputs: z.array(auditInputSchema).min(1, 'Provide at least one input').max(5),
  email: z.string().email('Invalid email address'),
});

export type CreateAuditBody = z.infer<typeof createAuditSchema>;

export const agentCompleteSchema = z.object({
  findings: z.array(z.unknown()).optional(),
  statistics: z.record(z.number()).optional(),
  reportMarkdown: z.string().optional(),
  reportUrl: z.string().url().optional(),
  error: z.string().optional(),
});

export const feedbackSchema = z.object({
  taskId: z.string().optional(),
  email: z.string().email().optional(),
  rating: z.number().int().min(1).max(5),
  content: z.string().max(5000).optional(),
});
