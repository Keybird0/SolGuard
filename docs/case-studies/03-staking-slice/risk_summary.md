# Risk Summary — rw12_staking_slice.rs

- **Contract**: `rw12_staking_slice.rs` (312 lines · Anchor 0.29 · mixed-legacy)
- **Decision**: proceed (AI cross-validated)
- **Findings**: 3 (1 High confirmed · 2 High/Medium pending analyst review)
- **Top severity**: High
- **Scan duration**: 19.0 s (LLM warm: 4.8 s)

## Executive Summary

This is a slice of a larger staking program that mixes an Anchor-typed "fast path" with a hand-rolled "legacy-position migration path" to preserve backwards compatibility with pre-Anchor stakers. The legacy path is the source of all three findings — it drops down to raw `AccountInfo` and manual `try_from_slice`, bypassing Anchor's discriminator/owner enforcement.

## Findings

### [High] Missing Owner Check — legacy position spoofing

- **Location**: `rw12_staking_slice.rs:251`
- **Rule**: `missing_owner_check`
- **Confidence**: 0.9
- **Ground truth**: ✅ match (line 251 expected)

**Reason** — `legacy_position` is declared as `AccountInfo<'info>` with no `#[account(owner = ...)]` constraint and no discriminator check. Any account whose byte layout happens to decode into `LegacyPosition` (via `try_from_slice`) is accepted.

**Recommendation** — Add an explicit `#[account(owner = crate::ID)]` constraint or migrate the legacy path to an Anchor `Account<'info, LegacyPosition>` wrapper. Until migrated, add a runtime `require_keys_eq!(legacy_position.owner, crate::ID)` check before any state-change.

### [High] Account Data Matching — manual deserialization bypasses Anchor guards

- **Location**: `rw12_staking_slice.rs:129`
- **Rule**: `account_data_matching`
- **Confidence**: 0.9

**Reason** — `LegacyPosition::try_from_slice(&raw)?` deserializes attacker-controlled bytes without validating the 8-byte Anchor discriminator or the account owner. Combined with the missing owner check above, this is a two-step spoof.

**Recommendation** — Use `Account::try_from_unchecked(&account_info)` + `account.exit(&crate::ID)?`, which enforces the discriminator, or rewrite `LegacyPosition` as a pre-Anchor bincode struct behind an explicit magic number the migration path checks first.

### [Medium] Integer Overflow — unchecked `reward_rate × multiplier`

- **Location**: `rw12_staking_slice.rs:142`
- **Rule**: `integer_overflow`
- **Confidence**: 0.9
- **Auditor note**: flagged as a **false positive** during ground-truth reconciliation — the upstream `multiplier` is a `u8` ceiling at 10, so the product fits in `u64`. However, the pattern is still brittle against future refactors that widen `multiplier`.

**Recommendation** — Replace with `pool.reward_rate.checked_mul(multiplier as u64).ok_or(ErrorCode::Overflow)?`. No runtime behavior change today; cheap regression insurance for tomorrow.

## Cross-cutting observation

All three findings cluster in the ~30-line "legacy-position migration" block (lines 125-155 and 245-265). An auditor can pinpoint the risky region in one glance; the fastest remediation path is to deprecate the legacy code path entirely once all stakers have migrated.
