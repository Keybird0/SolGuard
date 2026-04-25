// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// input-normalizer/ — convert heterogeneous AuditInput[] entries into
// `NormalizedInput[]` that both the OpenHarness agent prompt and the
// Python fallback runner can consume.
//
// Four kinds of inputs are supported:
//   - `github`           → clone → rust_source
//   - `contract_address` → RPC getAccountInfo → bytecode_only
//   - `whitepaper`       → fetch PDF/HTML → extract links → recurse
//   - `website`          → fetch HTML → extract links → recurse
//
// Every normalize-*.ts module is pure (no global state), returns a
// single NormalizedInput, and is independently testable via spawn / fetch
// / RPC injection. The orchestrator (`normalizeAll`) runs them in
// parallel and collects per-entry errors into `task.normalizeError`.
import path from 'node:path';
import { mkdirSync } from 'node:fs';
import { config } from '../config';
import { logger } from '../logger';
import type { AuditInput, NormalizedInput } from '../types';
import { normalizeGithub, type GithubNormalizerDeps } from './normalize-github';
import {
  normalizeContractAddress,
  type AddressNormalizerDeps,
} from './normalize-contract-address';
import { normalizeUrl, type UrlNormalizerDeps } from './normalize-url';

export type { GithubNormalizerDeps } from './normalize-github';
export type { AddressNormalizerDeps } from './normalize-contract-address';
export type { UrlNormalizerDeps } from './normalize-url';

export interface NormalizerDeps {
  github?: GithubNormalizerDeps;
  address?: AddressNormalizerDeps;
  url?: UrlNormalizerDeps;
  /** Max recursion depth when a website/whitepaper links to github/address. */
  maxRecursionDepth?: number;
}

export interface NormalizeResult {
  normalized: NormalizedInput;
  error?: string;
}

export function getWorkdirFor(taskId: string): string {
  const dir = path.resolve(config.auditWorkdir, taskId);
  mkdirSync(dir, { recursive: true });
  return dir;
}

export async function normalize(
  input: AuditInput,
  workdir: string,
  deps: NormalizerDeps = {},
  depth = 0,
): Promise<NormalizedInput> {
  const maxDepth = deps.maxRecursionDepth ?? 2;
  if (depth > maxDepth) {
    throw new Error(`normalize recursion limit ${maxDepth} exceeded`);
  }

  switch (input.type) {
    case 'github':
      return normalizeGithub(input, workdir, deps.github);
    case 'contract_address':
      return normalizeContractAddress(input, workdir, deps.address);
    case 'whitepaper':
    case 'website': {
      const result = await normalizeUrl(input, workdir, deps.url);
      if (result.kind !== 'lead_only') return result;
      // If the URL normalizer extracted a GitHub / address lead, recurse.
      const followUp = (result as { followUp?: AuditInput }).followUp;
      if (followUp) {
        logger.info(
          { origin: input, followUp, depth },
          'recursing into discovered lead from whitepaper/website',
        );
        return normalize(followUp, workdir, deps, depth + 1);
      }
      return result;
    }
    case 'more_info':
      // `more_info` is free-form context pasted into the AI prompt; nothing
      // to normalize. The audit-engine reads it from `task.inputs` directly.
      throw new Error('more_info is context-only and must be filtered before normalize()');
    default: {
      const exhaustive: never = input.type;
      throw new Error(`unknown input type: ${exhaustive as string}`);
    }
  }
}

export async function normalizeAll(
  inputs: AuditInput[],
  workdir: string,
  deps: NormalizerDeps = {},
): Promise<{ normalized: NormalizedInput[]; errors: string[] }> {
  // more_info entries are pure prompt context — never submitted to
  // per-kind normalizers (no clone / RPC / fetch).
  const filtered = inputs.filter((inp) => inp.type !== 'more_info');
  const results = await Promise.allSettled(
    filtered.map((inp) => normalize(inp, workdir, deps)),
  );
  const normalized: NormalizedInput[] = [];
  const errors: string[] = [];
  for (let i = 0; i < results.length; i++) {
    const r = results[i];
    const inp = filtered[i];
    if (!r || !inp) continue;
    if (r.status === 'fulfilled') {
      normalized.push(r.value);
    } else {
      const reason = (r as PromiseRejectedResult).reason;
      const msg = reason instanceof Error ? reason.message : String(reason);
      errors.push(`[${inp.type}=${inp.value}] ${msg}`);
      logger.warn({ err: msg, input: inp }, 'normalize failed');
    }
  }
  return { normalized, errors };
}
