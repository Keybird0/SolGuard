// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// Phase 6.5 · centralized error message dictionary. Backend returns
// `{ code, message }`; the `message` is usually accurate but terse /
// engineer-oriented. This module upgrades a known code to a
// "what happened + what to try" sentence pair so the UI never surfaces
// a bare "Request failed (500)" again.
//
// Adding a new mapping is intentionally cheap — just drop a new entry
// keyed by backend `code` (uppercase_snake_case). Unknown codes fall
// back to the original message plus a generic suggestion.

const DICT = {
  // --- Submit / validation ---------------------------------------
  VALIDATION_ERROR: {
    title: "We couldn't read one of the fields",
    hint: 'Please review the highlighted inputs and try again.',
  },
  BAD_TARGET: {
    title: 'A target looked invalid',
    hint: 'Each target needs at least one populated field — GitHub repo, program address, or URL.',
  },
  TOO_MANY_TARGETS: {
    title: 'Too many targets',
    hint: 'SolGuard audits up to 5 targets per batch. Split the rest into a second submission.',
  },
  EMAIL_INVALID: {
    title: 'Email looks malformed',
    hint: 'Double-check for typos — we deliver reports to this address.',
  },

  // --- Payment / wallet ------------------------------------------
  WALLET_NOT_FOUND: {
    title: 'Phantom extension not detected',
    hint: 'Install Phantom from phantom.app, unlock it, and try connecting again.',
  },
  WRONG_NETWORK: {
    title: 'Wallet is on the wrong cluster',
    hint: 'Switch Phantom to Devnet (Settings → Developer Settings → Change Network).',
  },
  INSUFFICIENT_BALANCE: {
    title: 'Not enough Devnet SOL',
    hint: 'Request an airdrop at faucet.solana.com or solfaucet.com, then refresh.',
  },
  PAYMENT_VERIFICATION_FAILED: {
    title: "We couldn't confirm your payment",
    hint: 'The transaction may still be finalizing — wait 30s and retry, or paste the signature manually.',
  },
  SIGNATURE_INVALID: {
    title: 'Signature could not be verified',
    hint: 'Paste the full base58 signature printed by your wallet / explorer and try again.',
  },
  PAYMENT_EXPIRED: {
    title: 'Payment window expired',
    hint: 'Go back, resubmit the batch, and pay within the shown countdown.',
  },

  // --- Tasks / pipeline ------------------------------------------
  NOT_FOUND: {
    title: 'Task not found',
    hint: 'The batch may have been purged. Start a new audit or check the shared link.',
  },
  AUDIT_FAILED: {
    title: 'The audit pipeline failed',
    hint: 'This is usually a transient network/agent hiccup — retry the submission once.',
  },
  NORMALIZATION_FAILED: {
    title: "We couldn't prepare your inputs",
    hint: 'Check that the GitHub repo is public and the URLs resolve; then retry.',
  },
  REPO_TOO_LARGE: {
    title: 'That repository is too large for a single audit',
    hint: 'Pin a smaller subfolder or submit a single program crate instead of a monorepo.',
  },

  // --- Infra -----------------------------------------------------
  RATE_LIMITED: {
    title: 'Too many requests — please slow down',
    hint: "You've hit the rate limit. Wait a minute and try again.",
  },
  UNAUTHORIZED: {
    title: 'Not authorized for this action',
    hint: 'Refresh the page to get a new session; if this persists, contact support.',
  },
  INTERNAL_ERROR: {
    title: 'Something broke on our side',
    hint: 'We logged it — please retry, and tell us on GitHub if it keeps happening.',
  },
  NETWORK_ERROR: {
    title: 'Network request failed',
    hint: 'Check your connection and retry. The server may also be briefly offline.',
  },
};

/**
 * Upgrade a backend-shaped error (or any Error) into a user-friendly
 * `{ title, hint, raw }` tuple. Never throws.
 */
export function friendlyError(err) {
  if (!err) {
    return {
      title: 'Something went wrong',
      hint: 'Please retry. If it keeps failing, reload the page.',
      raw: '',
    };
  }
  const code = err.code || err.errorCode || '';
  const base = DICT[code];
  const raw = (err.message || String(err)).slice(0, 400);
  if (base) {
    return { ...base, raw };
  }
  // Unknown code → show the original message and a generic retry hint.
  return {
    title: raw || 'Unexpected error',
    hint: 'Please retry; reload the page if it keeps failing.',
    raw,
  };
}

/**
 * Compose a single-line toast string (used where we don't have room
 * for a two-line "title + hint" card).
 */
export function friendlyToast(err) {
  const f = friendlyError(err);
  return `${f.title} — ${f.hint}`;
}
