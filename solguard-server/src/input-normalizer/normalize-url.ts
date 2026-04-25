// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// normalize-url.ts — whitepaper / website input handler.
//
// Strategy:
//  1. Fetch the URL (HTML or PDF, respects `input.type`).
//  2. Extract plain text (basic HTML tag stripping; PDFs fall back to
//     raw text markers since we don't bundle a PDF parser in Phase 3).
//  3. Heuristic lead-extraction: look for (a) github.com URLs, (b)
//     base58 Solana addresses. Optionally route through a tiny LLM
//     prompt when configured — but in Phase 3 default path we keep the
//     regex-only extractor to avoid adding another provider call.
//  4. If a GitHub URL or address is found, return a `lead_only` record
//     annotated with `followUp: AuditInput` so the orchestrator can
//     recurse (see normalizer index.ts).
//  5. Otherwise, persist the text snapshot and return `lead_only`.
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { config } from '../config';
import { logger } from '../logger';
import type { AuditInput, NormalizedInput } from '../types';
import { looksLikeSolanaAddress } from './normalize-contract-address';

export interface UrlNormalizerDeps {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  /**
   * Optional LLM lead extractor. Receives raw text, must return a list
   * of candidate AuditInputs. When omitted, we use a regex scanner.
   */
  llmExtractor?: (text: string) => Promise<AuditInput[]>;
}

export interface LeadOnlyWithFollowUp extends Extract<NormalizedInput, { kind: 'lead_only' }> {
  followUp?: AuditInput;
}

export async function normalizeUrl(
  input: AuditInput,
  workdir: string,
  deps: UrlNormalizerDeps = {},
): Promise<LeadOnlyWithFollowUp> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const timeoutMs = deps.timeoutMs ?? config.inputNormalizerTimeoutMs;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  timer.unref?.();

  logger.debug({ url: input.value, type: input.type }, 'url: fetching');
  let text = '';
  let status = 0;
  try {
    const res = await fetchImpl(input.value, {
      signal: controller.signal,
      headers: {
        'User-Agent': 'SolGuard/0.1 (+https://solguard.xyz)',
        Accept: 'text/html,application/pdf,application/xhtml+xml,*/*;q=0.8',
      },
      redirect: 'follow',
    });
    status = res.status;
    const body = await res.text();
    text = body.slice(0, 200_000);
  } catch (err) {
    clearTimeout(timer);
    throw err instanceof Error ? err : new Error(String(err));
  }
  clearTimeout(timer);

  const plain = stripHtml(text);

  const outDir = path.resolve(workdir, 'leads');
  mkdirSync(outDir, { recursive: true });
  const fileName = `${input.type}-${Date.now()}.txt`;
  const leadsJsonPath = path.join(outDir, fileName);
  writeFileSync(leadsJsonPath, plain, 'utf-8');

  const candidates = deps.llmExtractor
    ? await deps.llmExtractor(plain).catch((err) => {
        logger.warn({ err }, 'url: llm extractor failed, falling back to regex');
        return extractLeads(plain);
      })
    : extractLeads(plain);

  logger.info(
    { url: input.value, status, candidates: candidates.length, leadsJsonPath },
    'url: normalized',
  );

  return {
    kind: 'lead_only',
    leadsJsonPath,
    origin: { type: input.type, value: input.value },
    followUp: candidates[0],
  };
}

function stripHtml(raw: string): string {
  // Preserve href / src URLs before we strip tags so the lead extractor
  // can still find them in plain text.
  const hrefs = Array.from(raw.matchAll(/(?:href|src)\s*=\s*["']([^"']+)["']/gi))
    .map((m) => m[1])
    .filter((u): u is string => typeof u === 'string');
  const body = raw
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return [body, ...hrefs].join(' ').trim();
}

const GITHUB_URL_RE = /https?:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+/g;

export function extractLeads(text: string): AuditInput[] {
  const out: AuditInput[] = [];
  const seen = new Set<string>();

  const githubMatches = text.match(GITHUB_URL_RE) ?? [];
  for (const url of githubMatches) {
    const canonical = (url.split(/[?#]/)[0] ?? url).replace(/\.git$/, '');
    if (seen.has(canonical)) continue;
    seen.add(canonical);
    out.push({ type: 'github', value: canonical });
  }

  const tokens = text.split(/[\s,;"'`<>()[\]{}]+/);
  for (const token of tokens) {
    if (looksLikeSolanaAddress(token)) {
      const key = `addr:${token}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ type: 'contract_address', value: token });
    }
  }
  return out;
}
