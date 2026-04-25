# Contract Security Assessment — rw04_arbitrary_cpi.rs

- **Contract**: `rw04_arbitrary_cpi.rs`
- **Adapted from**: `coral-xyz/sealevel-attacks@24555d0 · programs/5-arbitrary-cpi/insecure`
- **Findings**: 1 Critical
- **Top severity**: Critical

## Scope

Single-file Anchor program with one instruction handler (`cpi`) and one account struct (`Cpi<'info>`). The scope covers the `#[program]` module (lines 16-43) and the `#[derive(Accounts)]` struct (lines 45-51). No on-chain state accounts are declared, so the entire attack surface is instruction-input validation.

## Methodology

1. `solana_parse` extracted 1 handler · 1 account struct · 4 accounts (`token_program`, `source`, `destination`, `authority`).
2. `solana_scan` rule pass flagged line 23 as a candidate `arbitrary_cpi` hit (confidence 0.3, hint).
3. `solana_semgrep` matched 2 patterns: `invoke-without-pda-check` and `unchecked-account`.
4. `solana_ai_analyze` (OpenAI `gpt-5.4`, temperature 0.05) cross-validated the hint against the account layout, confirmed `AccountInfo<'info>` ownership (no Anchor `Program<'info, Token>` type guard), and promoted the finding to confidence 0.9 with a Kill Signal decision of `proceed`.

## Findings

### [Critical] Arbitrary CPI — untrusted program substitution

- **Location**: `rw04_arbitrary_cpi.rs:23`
- **Rule**: `arbitrary_cpi`
- **Confidence**: 0.9

```rust
let ix = spl_token::instruction::transfer(
    ctx.accounts.token_program.key,   // line 23 — caller-controlled
    ctx.accounts.source.key,
    ctx.accounts.destination.key,
    ctx.accounts.authority.key,
    &[],
    amount,
)?;
invoke(
    &ix,
    &[
        ctx.accounts.source.clone(),
        ctx.accounts.destination.clone(),
        ctx.accounts.authority.clone(),
    ],
)?;
```

**Root cause** — `Cpi<'info>` declares `pub token_program: AccountInfo<'info>` (line 47), bypassing Anchor's program-type constraint (`Program<'info, Token>`) that would force a runtime equality check against `spl_token::ID`. The first argument to `spl_token::instruction::transfer` is the program ID used when `invoke(...)` resolves the target; because that value flows directly from the caller, any SBF program whose entrypoint matches the SPL Token instruction layout can be substituted.

**Impact** — Full loss of any tokens held in accounts the victim `authority` can sign for. The attacker program can:
- re-route `destination` to an attacker wallet
- ignore `amount` and call `burn` / `close_account` instead
- perform arbitrary follow-up CPIs using the victim's signer seeds (worst case: Token-2022 transfer hooks running unbounded attacker code)

**Remediation (preferred)**

```rust
use anchor_spl::token::{self, Token, Transfer};

#[derive(Accounts)]
pub struct Cpi<'info> {
    pub token_program: Program<'info, Token>,   // guarded
    pub source: AccountInfo<'info>,
    pub destination: AccountInfo<'info>,
    pub authority: Signer<'info>,
}

pub fn cpi(ctx: Context<Cpi>, amount: u64) -> Result<()> {
    let cpi_ctx = CpiContext::new(
        ctx.accounts.token_program.to_account_info(),
        Transfer {
            from: ctx.accounts.source.to_account_info(),
            to: ctx.accounts.destination.to_account_info(),
            authority: ctx.accounts.authority.to_account_info(),
        },
    );
    token::transfer(cpi_ctx, amount)
}
```

**Remediation (defensive, if Anchor types are not an option)**

```rust
require_keys_eq!(
    ctx.accounts.token_program.key(),
    anchor_spl::token::ID,
    CustomError::WrongTokenProgram,
);
```

## Defense-in-depth recommendations

- Add a Semgrep CI rule that fails on any `spl_token::instruction::*` called with an `AccountInfo`-typed `token_program` to catch regressions.
- Prefer `anchor_spl::token::transfer_checked` over `transfer` so the mint decimals / mint address are also validated at CPI time.
- Require a code-review sign-off whenever `invoke`, `invoke_signed` or `CpiContext::new` is introduced — flag them as high-signal changes in your PR template.

## Out of scope

- Runtime behavior of the authority's wallet (the fixture includes only the program).
- Upgradeability and governance of the program ID (Devnet deployment of the fixture uses a throwaway key).
