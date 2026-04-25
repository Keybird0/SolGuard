# Audit Checklist — rw04_arbitrary_cpi.rs

## Critical — must fix before mainnet

- [ ] (Critical) **Arbitrary CPI** @ `rw04_arbitrary_cpi.rs:23` — replace `token_program: AccountInfo<'info>` with `Program<'info, Token>` **or** add `require_keys_eq!(token_program.key(), anchor_spl::token::ID)` before `invoke`.
- [ ] Add an integration test that deploys a counterfeit `Evil111…` program, asserts the `cpi` handler rejects it with a recognizable error, and gate merges on that test.

## High — follow-up hardening

- [ ] Migrate the entire `invoke(...)` block to `anchor_spl::token::transfer(CpiContext::new(...))` so the program ID is resolved at account-struct time.
- [ ] Prefer `transfer_checked` over `transfer` to pin down mint + decimals at CPI.
- [ ] Add a Semgrep rule (`invoke-untyped-token-program`) to CI that fails on any `spl_token::instruction::*` called with a non-`Program<'info, Token>` argument.

## Medium — operational controls

- [ ] Document the expected `token_program` in the IDL so off-chain callers cannot accidentally pass a wrong program.
- [ ] Add a `CustomError::WrongTokenProgram` variant with a human-readable message so revert reasons are obvious in RPC logs.
- [ ] Enable `overflow-checks = true` in `Cargo.toml` release profile for defense in depth.

## Verification plan

- [ ] After remediation, re-run SolGuard: expected `findings=0`, `decision=proceed`.
- [ ] Run the fixture against Sealevel-Attacks' `5-arbitrary-cpi/secure` unit tests to confirm no regressions.
- [ ] Manually review the diff for any new `invoke` / `invoke_signed` call sites.
