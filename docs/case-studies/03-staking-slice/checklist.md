# Audit Checklist — rw12_staking_slice.rs

## Critical — fix before mainnet

_(none at Critical today; the two Highs together form a spoofing chain that behaves like Critical under exploit.)_

## High — must fix before mainnet

- [ ] (High) **Missing Owner Check** @ `rw12_staking_slice.rs:251` — replace `legacy_position: AccountInfo<'info>` with `Account<'info, LegacyPosition>` (enforces `owner == crate::ID` + discriminator).
- [ ] (High) **Account Data Matching** @ `rw12_staking_slice.rs:129` — drop `try_from_slice` on raw bytes. Either use `Account<'info, LegacyPosition>` (preferred) or add an explicit discriminator + owner check before the borsh decode.
- [ ] Add an integration test that points `legacy_position` at an account owned by a **different** program and asserts the handler returns `ErrorCode::WrongOwner`.
- [ ] Add an integration test that points `legacy_position` at a correctly-owned account with a **zeroed discriminator** and asserts rejection.

## Medium — should fix before mainnet

- [ ] (Medium) **Integer Overflow** @ `rw12_staking_slice.rs:142` — replace `pool.reward_rate * multiplier` with `checked_mul(... as u64).ok_or(ErrorCode::Overflow)?`.
- [ ] Enable `overflow-checks = true` in the Cargo release profile.
- [ ] Add a `require!(multiplier <= MAX_MULTIPLIER, ErrorCode::MultiplierTooLarge)` guard inside this handler so a future refactor cannot silently widen `multiplier` without tripping the guard.

## Low — hygiene

- [ ] Deprecate the legacy migration path once all stakers have migrated; removing the path removes all three findings mechanically.
- [ ] Document the expected byte layout of `LegacyPosition` in the program's IDL so off-chain tools and future auditors have a ground truth.
- [ ] Run SolGuard again after remediation — expected: 0 findings · decision=proceed.

## Verification plan

- [ ] Re-run SolGuard: target 0 findings after all High + Medium items are remediated.
- [ ] Run `cargo test --features integration` with the two new adversarial tests above.
- [ ] Manually review the diff for any new `AccountInfo<'info>` or `try_from_slice` call sites.
