import { z } from 'zod';
import type { InputType } from '../types';
import { validateMoreInfo } from './more-info-guard';

/**
 * Run the heuristic prompt-injection guard inside a Zod refine. Returns
 * a result object that Zod can attach to the right field path. Centralised
 * here so both the legacy `auditInputSchema` (single-target shape) and
 * the P4.6 `targetSchema` (Target card shape) share the same wording.
 */
function moreInfoRefine(value: string, ctx: z.RefinementCtx): void {
  const r = validateMoreInfo(value);
  if (!r.ok) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: r.reason,
      params: { code: 'MALICIOUS_INPUT', ruleId: r.ruleId },
    });
  }
}

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
  z.object({
    type: z.literal('more_info'),
    value: z
      .string()
      .min(1)
      .max(2000, 'More Info must be 2000 characters or fewer')
      .superRefine(moreInfoRefine),
  }),
]);

/** Legacy shape: a single Target expressed as a flat AuditInput[]. */
export const createAuditSchema = z.object({
  inputs: z.array(auditInputSchema).min(1, 'Provide at least one input').max(5),
  email: z.string().email('Invalid email address'),
});

export type CreateAuditBody = z.infer<typeof createAuditSchema>;

/**
 * Target schema: 5 optional fields, at least one must be present. `moreInfo`
 * is free-form text (<= 2000 chars) passed straight to the AI prompt. The
 * refine step keeps the error attached to the `targets[i]` path so the
 * frontend can highlight the right card.
 */
const emptyToUndef = (v: unknown): unknown =>
  typeof v === 'string' && v.trim() === '' ? undefined : v;

export const targetSchema = z
  .object({
    github: z.preprocess(
      emptyToUndef,
      z
        .string()
        .url()
        .regex(GITHUB_URL_REGEX, 'Expected https://github.com/owner/repo')
        .optional(),
    ),
    contractAddress: z.preprocess(
      emptyToUndef,
      z
        .string()
        .regex(SOLANA_ADDRESS_REGEX, 'Expected base58 Solana address (32-44 chars)')
        .optional(),
    ),
    whitepaper: z.preprocess(
      emptyToUndef,
      z.string().url('Expected a http(s) URL').optional(),
    ),
    website: z.preprocess(
      emptyToUndef,
      z.string().url('Expected a http(s) URL').optional(),
    ),
    moreInfo: z.preprocess(
      emptyToUndef,
      z
        .string()
        .min(1)
        .max(2000, 'More Info must be 2000 characters or fewer')
        .superRefine(moreInfoRefine)
        .optional(),
    ),
  })
  .refine(
    (t) => Boolean(t.github || t.contractAddress || t.whitepaper || t.website),
    {
      message:
        'Each Audit Target needs at least one primary field (GitHub / Program Address / Whitepaper / Website). "More Info" is supplementary only.',
    },
  );

export const createBatchSchema = z.object({
  targets: z.array(targetSchema).min(1, 'Provide at least one Audit Target').max(5),
  email: z.string().email('Invalid email address'),
});

export type CreateBatchBody = z.infer<typeof createBatchSchema>;
export type Target = z.infer<typeof targetSchema>;

const severitySchema = z.enum(['Critical', 'High', 'Medium', 'Low', 'Info']);

const findingSchema = z
  .object({
    id: z.string(),
    ruleId: z.string().optional(),
    severity: severitySchema,
    title: z.string(),
    location: z.string(),
    description: z.string(),
    impact: z.string(),
    recommendation: z.string(),
    codeSnippet: z.string().optional(),
    confidence: z.number().optional(),
    killSignal: z
      .object({
        isValid: z.boolean(),
        reason: z.string(),
      })
      .optional(),
  })
  .passthrough();

const statisticsSchema = z
  .object({
    critical: z.number().int().nonnegative(),
    high: z.number().int().nonnegative(),
    medium: z.number().int().nonnegative(),
    low: z.number().int().nonnegative(),
    info: z.number().int().nonnegative(),
    total: z.number().int().nonnegative(),
  })
  .partial();

export const agentCompleteSchema = z.object({
  status: z.enum(['completed', 'failed']).optional(),
  findings: z.array(findingSchema).optional(),
  statistics: statisticsSchema.optional(),
  reportMarkdown: z.string().optional(),
  reportUrl: z.string().url().optional(),
  error: z.string().optional(),
});

export const paymentPushSchema = z.object({
  signature: z
    .string()
    .min(32, 'Invalid transaction signature')
    .max(120, 'Invalid transaction signature'),
});

export type PaymentPushBody = z.infer<typeof paymentPushSchema>;

/**
 * Map a Target (from the UI) to a flat AuditInput[] that the audit pipeline
 * already understands. Non-empty fields are emitted in a stable order.
 */
export function targetToInputs(t: Target): { type: InputType; value: string }[] {
  const out: { type: InputType; value: string }[] = [];
  if (t.github) out.push({ type: 'github', value: t.github });
  if (t.contractAddress) out.push({ type: 'contract_address', value: t.contractAddress });
  if (t.whitepaper) out.push({ type: 'whitepaper', value: t.whitepaper });
  if (t.website) out.push({ type: 'website', value: t.website });
  if (t.moreInfo) out.push({ type: 'more_info', value: t.moreInfo });
  return out;
}

export const feedbackSchema = z.object({
  taskId: z.string().optional(),
  email: z.string().email().optional(),
  rating: z.number().int().min(1).max(5),
  content: z.string().max(5000).optional(),
});

export type FeedbackBody = z.infer<typeof feedbackSchema>;
