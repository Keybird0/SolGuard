// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// Heuristic prompt-injection / malicious input guard for the `more_info`
// free-text field. Runs SYNCHRONOUSLY in the Zod refine path — zero LLM
// calls, zero RPC, zero filesystem.
//
// Why heuristic-first? Per `docs/03-现有材料与项目规划/04-实现预期.md` B1
// + C4-ii, "AI 初步研判恶意输入" is a real expectation, but the value of
// adding a 1-2s LLM round-trip on every submission is dubious in a v0.8
// MVP — four nested defences already exist (Zod format · SSRF reject in
// normalize-url · delimited-block prompt envelope · HMAC callback). The
// remaining attack surface is the user-controlled "more_info" string
// being concatenated into the audit prompt; a deterministic blacklist
// covers the practical injection corpus without spending tokens.
//
// Optional LLM fallback path lives in
// `skill/.../references/input-guard-prompt.md` (debian-style "asset
// ready, default off"). Wire it via INPUT_GUARD_LLM_FALLBACK=true if
// upstream traffic shows a sustained miss rate.
//
// Public API:
//   validateMoreInfo(text: string): GuardResult
//
// Returns either { ok: true } or { ok: false, reason }. The reason is
// safe to surface to the user — it states *what triggered* but never
// echoes the offending substring (preventing reflection attacks).

export interface GuardOk {
  ok: true;
}
export interface GuardReject {
  ok: false;
  /** Stable machine-readable rule id; user-friendly translation is
   *  done by the frontend's `errors.js` dictionary. */
  ruleId: string;
  /** Short reason for the operator log, never echoes the offending
   *  text directly. */
  reason: string;
}
export type GuardResult = GuardOk | GuardReject;

// =============================================================================
// Heuristic rules (case-insensitive unless noted; ordered by specificity)
// =============================================================================

interface Rule {
  id: string;
  test: (text: string) => boolean;
  reason: string;
}

// Phrases that show up almost exclusively in prompt-injection payloads.
// Keep this list short — every entry should be something a legitimate
// audit submitter would never write to "give context to a Solana audit."
const INJECTION_PHRASES: readonly string[] = [
  'ignore previous instructions',
  'ignore all previous instructions',
  'ignore the above',
  'disregard the prior',
  'disregard previous',
  'forget your instructions',
  'forget the above',
  'system prompt',
  'reveal your prompt',
  'show me your instructions',
  'you are now',
  'act as if',
  'pretend you are',
  'jailbreak',
  'do anything now',
  'developer mode',
  'override safety',
];

// Tokens that indicate an attempt to break the delimited-block prompt
// envelope (`<CODE>...</CODE>` / `<EVIDENCE>...</EVIDENCE>` etc.).
const ENVELOPE_BREAKERS: readonly string[] = [
  '</code>',
  '</evidence>',
  '<|',
  '|>',
  '[/inst]',
  '<<sys>>',
  '<</sys>>',
  '"role": "system"',
  '"role":"system"',
  '<im_start>',
  '<im_end>',
  '<|im_start|>',
  '<|im_end|>',
];

// Permitted URL schemes inside more_info. Everything else (file://,
// data:, javascript:, raw IPv4, etc.) is rejected.
const URL_SCHEME_RE = /(^|[\s(])([a-z][a-z0-9+\-.]*):/gi;
const ALLOWED_SCHEMES = new Set(['http', 'https', 'mailto']);

const RULES: readonly Rule[] = [
  {
    id: 'INJECTION_PHRASE',
    test: (text) => {
      const lc = text.toLowerCase();
      return INJECTION_PHRASES.some((p) => lc.includes(p));
    },
    reason: 'moreInfo contains a known prompt-injection phrase',
  },
  {
    id: 'ENVELOPE_BREAKER',
    test: (text) => {
      const lc = text.toLowerCase();
      return ENVELOPE_BREAKERS.some((p) => lc.includes(p));
    },
    reason: 'moreInfo contains a delimiter sequence that could escape the prompt envelope',
  },
  {
    // Order matters: check OVERLONG_LINE before LONG_BASE64_BLOCK because
    // many overlong lines happen to contain only base64-alphabet chars
    // and the broader "this single line is too long" signal is what we
    // want to surface.
    id: 'OVERLONG_LINE',
    test: (text) => text.split(/\r?\n/).some((line) => line.length >= 500),
    reason: 'moreInfo contains a single line ≥ 500 chars — typical injection vector',
  },
  {
    id: 'LONG_BASE64_BLOCK',
    test: (text) => /[A-Za-z0-9+/=]{200,}/.test(text),
    reason: 'moreInfo contains a long base64-like block (≥ 200 chars) — suspected payload smuggling',
  },
  {
    id: 'DISALLOWED_URL_SCHEME',
    test: (text) => {
      // Reset regex state between invocations (global flag).
      URL_SCHEME_RE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = URL_SCHEME_RE.exec(text)) !== null) {
        const scheme = m[2]?.toLowerCase();
        if (!scheme) continue;
        if (!ALLOWED_SCHEMES.has(scheme)) return true;
      }
      return false;
    },
    reason: 'moreInfo contains a URL with a disallowed scheme (only http/https/mailto are accepted)',
  },
  {
    id: 'CONTROL_CHARS',
    // Reject ANSI escape sequences and other terminal-control payloads.
    // The eslint `no-control-regex` rule (disabled inline below) flags
    // intentional control-byte ranges; we *want* to match them here as
    // the whole point is to surface terminal escapes / null bytes.
    test: (text) => {
      for (let i = 0; i < text.length; i++) {
        const code = text.charCodeAt(i);
        if (
          (code >= 0x00 && code <= 0x08) ||
          code === 0x0b ||
          code === 0x0c ||
          (code >= 0x0e && code <= 0x1f) ||
          code === 0x7f
        ) {
          return true;
        }
      }
      return false;
    },
    reason: 'moreInfo contains control characters (terminal-escape / null bytes)',
  },
];

// =============================================================================
// Public API
// =============================================================================

/**
 * Run all heuristic rules over `text`. First-match-wins — we report the
 * earliest tripped rule rather than aggregate, since the user only needs
 * one actionable error.
 *
 * Empty / whitespace-only text is treated as a pass (a real "no
 * more_info supplied" case is handled upstream by Zod's `optional`).
 */
export function validateMoreInfo(text: string): GuardResult {
  if (!text || text.trim().length === 0) return { ok: true };
  for (const rule of RULES) {
    try {
      if (rule.test(text)) {
        return { ok: false, ruleId: rule.id, reason: rule.reason };
      }
    } catch {
      // A rule misfiring (e.g. catastrophic regex backtracking) must
      // never crash the request. Skip the rule and let later ones run.
      continue;
    }
  }
  return { ok: true };
}
