# Risk Summary — rw04_arbitrary_cpi.rs

- **Contract**: `rw04_arbitrary_cpi.rs` (51 lines · Anchor 0.29)
- **Decision**: proceed (AI cross-validated)
- **Findings**: 1
- **Top severity**: Critical
- **Scan duration**: 12.9 s (LLM warm: 4.1 s)

## Executive Summary

A single, fully-exploitable **arbitrary CPI** vulnerability was identified. The program accepts a caller-supplied `token_program` as a raw `AccountInfo<'info>` and immediately hands it to `invoke(...)` with the source token account, destination token account and user signer attached. Any caller can substitute a malicious program ID that honors the SPL Token wire format but swaps recipients or mints unbacked balances.

This is the Sealevel "classic" — the same shape that drained funds from several 2022-era Solana programs — and there are **no mitigating controls** anywhere in the critical path (no `Program<'info, Token>` type, no `require_keys_eq!`, no hard-coded `spl_token::ID` comparison).

## Findings

### [Critical] Arbitrary CPI — untrusted program substitution

- **Location**: `rw04_arbitrary_cpi.rs:23`
- **Rule**: `arbitrary_cpi`
- **Confidence**: 0.9
- **Category**: CWE-20 Improper Input Validation · Solana "Arbitrary CPI" (Sealevel-Attacks §5)

**Reason** — The instruction program ID is taken directly from the caller-controlled `token_program` `AccountInfo` and is never constrained to `anchor_spl::token::ID`. A malicious program can be supplied and invoked with the original instruction's signer privileges, so the attacker can override `transfer_checked` and execute any logic on the attached accounts.

**Exploit path**

1. Attacker deploys a Solana program `Evil111...` that exports a function with the same discriminator as `spl_token::instruction::transfer`.
2. Attacker calls the `cpi` handler supplying `Evil111...` for `token_program`, their attacker-controlled account for `destination`, and their `Signer` for `authority`.
3. `invoke(...)` at line 33 runs the attacker's code with the victim's `source` account and `authority` signer privileges — no signer check fires because the victim never runs this path.
4. Attacker drains the `source` balance or calls arbitrary cross-program instructions under the victim's authority.

**Recommendation** — Constrain `token_program` to the canonical SPL Token program using `Program<'info, Token>` or `require_keys_eq!(token_program.key(), spl_token::ID)` before `invoke`, and prefer Anchor CPI helpers (`anchor_spl::token::transfer(CpiContext::new(...))`) over manual `invoke`. Both Anchor idioms enforce the program ID at account-resolve time and are mechanically checked by `cargo check`.
