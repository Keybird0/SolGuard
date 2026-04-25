# Contract Security Assessment — rw12_staking_slice.rs

- **Contract**: `rw12_staking_slice.rs` (312 lines)
- **Findings**: 3 (1 TP, 2 auditor-review)
- **Top severity**: High

## Scope

A slice from a production-style staking program. The file contains:

- 6 instruction handlers (`initialize_pool`, `stake`, `apply_rewards`, `unstake`, `migrate_legacy`, `close_pool`)
- 4 state accounts (`StakePool`, `Position`, `LegacyPosition`, `RewardsVault`)
- A mixed Anchor-typed / hand-rolled `AccountInfo` account struct for the legacy migration path

## Methodology

1. `solana_parse` extracted 6 handlers · 4 account structs · 23 accounts. The mixed typing (`Account<'info, T>` + `AccountInfo<'info>`) flagged for the AI stage.
2. `solana_scan` produced 2 hints — `missing_owner_check` at line 251 (confidence 0.3) and `raw_arithmetic` at line 142 (confidence 0.3).
3. `solana_semgrep` matched 4 patterns — `unchecked-account` ×2, `raw-arithmetic` ×1, `manual-deserialize` ×1.
4. `solana_ai_analyze` (OpenAI `gpt-5.4`, temperature 0.05) cross-validated scan + semgrep hits and **promoted** three of them to confidence 0.9. The analyzer's Kill Signal returned `proceed`.
5. `solana_report` emitted the 3-tier report.

## Findings

### [High] Missing Owner Check

- **Location**: `rw12_staking_slice.rs:251`
- **Rule**: `missing_owner_check`

```rust
#[derive(Accounts)]
pub struct MigrateLegacy<'info> {
    #[account(mut)]
    pub pool: Account<'info, StakePool>,
    // VULN: no owner guard, no discriminator, no PDA binding
    pub legacy_position: AccountInfo<'info>,   // line 251
    pub authority: Signer<'info>,
}
```

**Root cause** — `legacy_position` is a raw `AccountInfo<'info>` with none of Anchor's automatic owner / discriminator checks. Any account whose byte layout happens to decode into `LegacyPosition` is accepted.

**Impact** — Attacker can point `legacy_position` at any account (e.g. a closed account reclaimed by the attacker, or a system-program-owned lamport carrier) whose data bytes spoof a staker's `amount_staked` field, then claim rewards proportional to the fake stake.

**Remediation**

```rust
#[account(owner = crate::ID, has_one = authority)]
pub legacy_position: Account<'info, LegacyPosition>,
```

Migrating to `Account<'info, T>` enforces `owner == crate::ID` and discriminator check at account-resolve time (cheap) and eliminates the whole class.

### [High] Account Data Matching

- **Location**: `rw12_staking_slice.rs:129`
- **Rule**: `account_data_matching`

```rust
// inside migrate_legacy, after reading legacy_position.try_borrow_data()?
let view = LegacyPosition::try_from_slice(&raw)?;   // line 129
```

**Root cause** — `try_from_slice` is raw borsh deserialization. It does not check the 8-byte Anchor discriminator (which would prove the bytes were written by this program's `LegacyPosition` type) nor the account owner.

**Impact** — Combined with the missing owner check above, this is a two-step account spoof: attacker controls bytes via a program they own, then feeds the result into the staking program's reward calculation.

**Remediation** — Either migrate to `Account<'info, LegacyPosition>` (preferred), or if raw access must remain, prepend the discriminator check manually:

```rust
require!(
    legacy_position.owner == &crate::ID,
    ErrorCode::WrongOwner,
);
let mut raw: &[u8] = &legacy_position.try_borrow_data()?;
let disc = <LegacyPosition as anchor_lang::Discriminator>::DISCRIMINATOR;
require!(raw.starts_with(&disc), ErrorCode::WrongDiscriminator);
let view = LegacyPosition::try_from_slice(&raw[8..])?;
```

### [Medium] Integer Overflow — `reward_rate × multiplier`

- **Location**: `rw12_staking_slice.rs:142`
- **Rule**: `integer_overflow`

```rust
let new_rate = ctx.accounts.pool.reward_rate * multiplier;   // line 142
```

**Root cause** — Unchecked multiplication. Today `multiplier: u8 ≤ 10` is enforced at a caller's boundary, so the product cannot exceed `10 × u64::MAX`, but:

- the `u8 → u64` promotion is implicit,
- the caller-side cap is not guarded by a `require!` in this file (the analyst would have to trace a different crate to verify), and
- any future refactor that widens `multiplier` to `u64` would silently enable overflow.

**Impact (if the upstream cap is removed)** — Attackers could inflate `reward_rate` to any value, draining the rewards vault on the next `apply_rewards` cycle.

**Remediation**

```rust
let new_rate = ctx.accounts.pool.reward_rate
    .checked_mul(multiplier as u64)
    .ok_or(ErrorCode::Overflow)?;
```

Or enable `overflow-checks = true` in the release profile for defense in depth.

## Cross-cutting observations

- **Legacy-path blast radius.** All three findings cluster in the legacy migration code (lines 125-155, 245-265). If stakers have already migrated to the Anchor-typed path, the cheapest fix is to deprecate and ultimately remove the legacy handler altogether.
- **Testing coverage gap.** No test in the slice exercises the migration path with an adversarially-crafted `legacy_position`. We recommend adding an integration test that tries to migrate an account owned by a **different** program and asserts the handler rejects it.

## Out of scope

- Whole-program economic modeling (reward schedule, APR caps) — SolGuard does not reason about business logic.
- Off-chain migration tooling and UX for legacy stakers.
- Upgrade authority key management.
