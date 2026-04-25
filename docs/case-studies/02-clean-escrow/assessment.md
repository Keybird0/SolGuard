# Contract Security Assessment — rw08_clean_escrow.rs

- **Contract**: `rw08_clean_escrow.rs` (172 lines)
- **Findings**: 0
- **Top severity**: None

## Scope

Two-party SPL escrow program with two instruction handlers (`initialize`, `exchange`), one state account (`EscrowAccount`) and a PDA-owned vault. This assessment covers all 172 lines.

## Methodology

1. `solana_parse` extracted 2 handlers · 3 account structs · 11 accounts. `Escrow PDA` and `vault_authority PDA` identified with canonical bump storage.
2. `solana_scan` produced **0 rule hints** — no matches on the 7 built-in rules.
3. `solana_semgrep` produced 1 hit (arithmetic on `escrow_account.taker_amount`), suppressed by the AI analyzer as a false positive after tracing the source.
4. `solana_ai_analyze` ran the cross-validation + exploration pass with `gpt-5.4`; Kill Signal = `proceed`, decision = no-findings.
5. `solana_report` emitted the clean 3-tier report.

## What was checked

### Signer / authority presence — **pass**

- `initialize` requires `initializer: Signer<'info>` (line 20).
- `exchange` requires `taker: Signer<'info>` (line 38) and validates the escrow's stored `initializer_key` matches the pending counterparty.

### Owner validation — **pass**

All state accounts are declared with Anchor's `Account<'info, EscrowAccount>` wrapper which enforces `owner == crate::ID` at discriminator-check time. Token accounts are wrapped in `anchor_spl::token::TokenAccount` which in turn enforces `owner == spl_token::ID`.

### Integer arithmetic — **pass**

The only arithmetic in mutable paths is the token-amount equality check (`escrow_account.initializer_amount == amount`, line 87). No multiplication, no pre-computed rate × quantity, no implicit casts on caller-supplied values.

### CPI target validation — **pass**

Both CPI sites use `token_program: Program<'info, Token>` (lines 45, 71). Every `transfer` CPI goes through `anchor_spl::token::transfer_checked(CpiContext::new_with_signer(...))`, which pins the mint and the program ID.

### PDA derivation — **pass**

- Escrow PDA: `seeds = [b"escrow", initializer.key().as_ref()], bump` with `bump` stored in the account and re-supplied to `invoke_signed`.
- Vault authority: `seeds = [b"vault", escrow.key().as_ref()], bump = escrow.vault_bump`.

No `Pubkey::find_program_address` loop is re-run during exchange (which would be redundant with the stored bump).

### Account data matching — **pass**

No manual deserialization of raw `AccountInfo`. The single `transmute`-adjacent pattern (`try_from_slice`) is **not** present in this file.

## Suppressed scan hits

| Source | Hit | Reason for suppression |
|---|---|---|
| semgrep `raw-arithmetic` | `escrow_account.taker_amount` comparison | Not an arithmetic operation — AI analyzer re-classified after reading the surrounding statement (`require!(...eq)`). |

## Out of scope

- Business-logic correctness (refund windows, cancellation semantics).
- Economic incentives (who pays fees, slippage).
- Off-chain wallet UX (approval prompts, token-2022 hook surfaces).
- Upgrade authority key management.
