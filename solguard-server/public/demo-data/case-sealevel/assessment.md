# Assessment — Audit Report — benchmark_repo · 11 target(s)

- Targets audited: 11
- Findings: 16
- Top severity: Critical

## Targets audited

- `lib.rs` [insecure_sample] · scanner=assisted · ai=completed · findings=1
- `lib.rs` [insecure_sample] · scanner=zero_hints · ai=completed · findings=1
- `lib.rs` [insecure_sample] · scanner=zero_hints · ai=completed · findings=1
- `lib.rs` [insecure_sample] · scanner=zero_hints · ai=completed · findings=1
- `lib.rs` [insecure_sample] · scanner=zero_hints · ai=completed · findings=2
- `lib.rs` [insecure_sample] · scanner=assisted · ai=completed · findings=4
- `lib.rs` [insecure_sample] · scanner=assisted · ai=completed · findings=2
- `lib.rs` [insecure_sample] · scanner=zero_hints · ai=completed · findings=1
- `lib.rs` [insecure_sample] · scanner=zero_hints · ai=completed · findings=1
- `lib.rs` [insecure_sample] · scanner=zero_hints · ai=completed · findings=1
- `lib.rs` [insecure_sample] · scanner=zero_hints · ai=completed · findings=1

## Findings

### [Critical] Arbitrary Cpi
- **Location**: `lib.rs:12`
- **Rule**: `arbitrary_cpi`
- **Reason**: The CPI target program comes entirely from ctx.accounts.token_program and is never checked against spl_token::ID. An attacker can supply a malicious program account, receive a crafted transfer instruction, and execute arbitrary logic with the provided accounts.
- **Recommendation**: Whitelist the callee with require_keys_eq!(token_program.key(), spl_token::ID) or use Program<'info, Token> and anchor_spl::token::transfer to bind the CPI to the real SPL Token program.

```rust
ctx.accounts.token_program.key,
```

### [High] Missing Signer Check
- **Location**: `lib.rs:16`
- **Rule**: `missing_signer_check`
- **Reason**: The authority account is declared as raw AccountInfo without Signer<'info> or a manual is_signer check, so any transaction can supply an arbitrary public key and spoof the logged authority identity.
- **Recommendation**: Require signer authorization by changing the field to Signer<'info> or adding #[account(signer)] / a manual require!(authority.is_signer, ...) check before using the account as an authority.

```rust
authority: AccountInfo<'info>
```

### [High] Account Data Matching
- **Location**: `programs/1-account-data-matching/insecure/src/lib.rs:20`
- **Rule**: `account_data_matching`
- **Reason**: The instruction manually deserializes an arbitrary token account from raw AccountInfo but never checks that authority.key equals the token account owner. Any signer can pass someone else's token account and read/log its balance, violating expected account-to-authority matching.
- **Recommendation**: Use Account<'info, TokenAccount> with an Anchor constraint like #[account(constraint = authority.key() == token.owner)] or manually require_keys_eq!(authority.key(), token.owner) after unpacking.

```rust
token: AccountInfo<'info>,
```

### [High] Missing Owner Check
- **Location**: `programs/2-owner-checks/insecure/src/lib.rs:13`
- **Rule**: `missing_owner_check`
- **Reason**: The instruction deserializes arbitrary account data as an SPL Token Account using SplTokenAccount::unpack but never verifies ctx.accounts.token.owner == spl_token::ID. An attacker can supply a non-token account they control whose bytes mimic a token account, causing forged owner and amount fields to be trusted.
- **Recommendation**: Verify the account owner before unpacking, e.g. require_keys_eq!(*ctx.accounts.token.owner, spl_token::ID), or use Account<'info, TokenAccount> with Anchor constraints so owner and layout checks are enforced automatically.

```rust
let token = SplTokenAccount::unpack(&ctx.accounts.token.data.borrow())?;
```

### [High] Account Data Matching
- **Location**: `programs/3-type-cosplay/insecure/src/lib.rs:11`
- **Rule**: `account_data_matching`
- **Reason**: The program manually deserializes the User struct from raw account data without using Anchor's Account<T> wrapper or checking a discriminator field, allowing attacker-owned accounts with crafted data to be accepted.
- **Recommendation**: Use Anchor's Account<'info, User> type for the user account to enforce discriminator and owner checks automatically, or explicitly check the account owner and discriminator before deserialization.

```rust
let user = User::try_from_slice(&ctx.accounts.user.data.borrow()).unwrap();
```

### [High] Missing Owner Check
- **Location**: `programs/3-type-cosplay/insecure/src/lib.rs:12`
- **Rule**: `missing_owner_check`
- **Reason**: The program checks the user account owner after deserialization, which is too late and ineffective because the deserialization already trusts the data. This allows an attacker to supply a malicious account with arbitrary data that passes the deserialization step.
- **Recommendation**: Perform the owner check before deserializing the account data to prevent processing attacker-controlled data, or better, use Anchor's Account<'info, User> which enforces owner and discriminator checks automatically.

```rust
if ctx.accounts.user.owner != ctx.program_id {
```

### [High] Account Data Matching
- **Location**: `lib.rs:16`
- **Rule**: `account_data_matching`
- **Reason**: The program reads and writes a raw AccountInfo using Borsh without any owner, discriminator, or initialization check. An attacker can pass arbitrary account data that parses as User and have this instruction overwrite authority.
- **Recommendation**: Use #[account(init)] with Account<'info, User> so Anchor enforces ownership and discriminator checks, or explicitly verify user.owner == crate::ID and store/check an initialized discriminator before mutation.

```rust
let mut storage = ctx.accounts.user.try_borrow_mut_data()?; user.serialize(storage.deref_mut()).unwrap();
```

### [High] Semgrep:Assets.Semgrep-Rules.Solana-Manual-Accountinfo-Deserialize
- **Location**: `lib.rs:12`
- **Rule**: `semgrep:assets.semgrep-rules.solana-manual-accountinfo-deserialize`
- **Reason**: User::try_from_slice is performed on a raw AccountInfo, bypassing Anchor account validation. Because user is not typed as Account<'info, User> and has no owner/discriminator guard, attacker-controlled bytes can be accepted as a valid User state.
- **Recommendation**: Replace the raw AccountInfo with Account<'info, User> or add explicit owner and initialization checks before deserializing and mutating the account data.

```rust
let mut user = User::try_from_slice(&ctx.accounts.user.data.borrow()).unwrap();
```

### [High] Uninitialized Account
- **Location**: `lib.rs:11`
- **Rule**: `uninitialized_account`
- **Reason**: initialize has no one-time initialization guard. Any writable account whose bytes deserialize as User can be reinitialized, and previously initialized state can be overwritten because no discriminator or initialized flag is checked before assignment.
- **Recommendation**: Introduce an initialized/discriminator field and reject repeated initialization, or switch to Anchor #[account(init)] / Account<'info, User> so creation and first initialization are enforced by the framework.

```rust
pub fn initialize(ctx: Context<Initialize>) -> ProgramResult {
```

### [High] Missing Owner Check
- **Location**: `lib.rs:31`
- **Rule**: `missing_owner_check`
- **Reason**: The user account is accepted as plain AccountInfo and never checked to be owned by this program. The instruction may deserialize and mutate data from accounts owned by another program or unrelated system accounts, violating account ownership assumptions.
- **Recommendation**: Constrain user as Account<'info, User> or add require_keys_eq!(*ctx.accounts.user.owner, crate::ID) before deserializing and writing.

```rust
user: AccountInfo<'info>
```

### [High] Missing Signer Check
- **Location**: `lib.rs:33`
- **Rule**: `missing_signer_check`
- **Reason**: The transfer CPI uses authority.key as the token authority but the account is only AccountInfo with no signer constraint. A caller can pass any pubkey as authority, and because invoke forwards signer metas from the outer instruction, the program never enforces that this authority actually signed.
- **Recommendation**: Change authority to Signer<'info> or add #[account(signer)] so the runtime and Anchor enforce a real signature before building the token transfer CPI.

```rust
authority: AccountInfo<'info>
```

### [High] Pda Derivation Error
- **Location**: `programs/7-bump-seed-canonicalization/insecure/src/lib.rs:10`
- **Rule**: `pda_derivation_error`
- **Reason**: The instruction accepts a caller-supplied bump and validates the PDA with create_program_address instead of deriving the canonical bump. Multiple valid bumps can exist for the same seed set, so an attacker can pass a non-canonical PDA they control or initialized separately and have the program treat it as the legitimate account.
- **Recommendation**: Derive the PDA with Pubkey::find_program_address and reject any supplied bump that does not equal the canonical bump, or preferably enforce seeds and bump in the Anchor account constraints with #[account(seeds = [key.to_le_bytes().as_ref()], bump)].

```rust
Pubkey::create_program_address(&[key.to_le_bytes().as_ref(), &[bump]], ctx.program_id)?;
```

### [High] Pda Derivation Error
- **Location**: `programs/8-pda-sharing/insecure/src/lib.rs:11`
- **Rule**: `pda_derivation_error`
- **Reason**: The signer seeds for the PDA are derived from pool.mint and pool.bump, but the pool account is not constrained with matching #[account(seeds=..., bump=...)] checks. This lets an attacker supply a pool whose stored fields make the program sign for a shared PDA derived only from a common mint, enabling unauthorized withdrawal from another user's vault if that PDA owns it.
- **Recommendation**: Bind the pool account to its canonical PDA with #[account(seeds = [withdraw_destination.key().as_ref()], bump = pool.bump)] or equivalent unique user/domain-separated seeds, and ensure invoke_signed uses the exact same seed domain.

```rust
let seeds = &[ctx.accounts.pool.mint.as_ref(), &[ctx.accounts.pool.bump]];
```

### [Medium] Custom:Sysvar Spoofing
- **Location**: `programs/10-sysvar-address-checking/insecure/src/lib.rs:17`
- **Rule**: `custom:sysvar_spoofing`
- **Reason**: The rent account is accepted as a raw AccountInfo without any address check or Sysvar type enforcement, so a caller can pass an arbitrary account instead of the real Rent sysvar. Any later logic that trusts this account as the rent sysvar would be spoofable.
- **Recommendation**: Use Anchor's Sysvar<'info, Rent> type for the account, or explicitly enforce require_keys_eq!(ctx.accounts.rent.key(), anchor_lang::solana_program::sysvar::rent::ID) before using it as a sysvar.

```rust
rent: AccountInfo<'info>,
```

### [Medium] Custom:Duplicate Mutable Accounts
- **Location**: `programs/6-duplicate-mutable-accounts/insecure/src/lib.rs:21`
- **Rule**: `custom:duplicate_mutable_accounts`
- **Reason**: The instruction accepts two writable Account<User> inputs but never enforces that user_a and user_b are different accounts. An attacker can pass the same account for both parameters, causing aliasing of mutable state and defeating any intended two-account update semantics.
- **Recommendation**: Add an explicit distinctness check such as #[account(constraint = user_a.key() != user_b.key())] on the accounts struct or require_keys_neq!(ctx.accounts.user_a.key(), ctx.accounts.user_b.key()) at instruction entry.

```rust
user_a: Account<'info, User>,
```

### [Medium] Custom:Closing Account Error
- **Location**: `programs/9-closing-accounts/insecure/src/lib.rs:9`
- **Rule**: `custom:closing_account_error`
- **Reason**: The instruction manually drains lamports from an Anchor account but never marks the account as closed by zeroing data and writing the closed-account discriminator. The same account can later receive lamports again and be deserialized as a valid Data account, enabling account revival and repeated unintended reuse after an apparent close.
- **Recommendation**: Use Anchor's #[account(mut, close = destination)] constraint or, if closing manually, zero the account data and write CLOSED_ACCOUNT_DISCRIMINATOR after transferring lamports so the account cannot be revived as a valid program account.

```rust
pub fn close(ctx: Context<Close>) -> ProgramResult {
```

