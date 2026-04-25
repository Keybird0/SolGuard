// SPDX-License-Identifier: MIT
//! Adversarial fixture: "fake" missing signer.
//!
//! Looks identical to fixture 01 at the type level — `authority` is a raw
//! `AccountInfo<'info>` without `#[account(signer)]` — but the instruction
//! body calls `require_keys_eq!` against `config.admin` before doing
//! anything sensitive. Our scan/semgrep layer DOES fire; the AI should
//! mark the hit as `is_valid=false` (rejected).

use anchor_lang::prelude::*;

declare_id!("FakeMs1111111111111111111111111111111111111");

#[program]
pub mod fake_missing_signer {
    use super::*;

    pub fn withdraw(ctx: Context<Withdraw>, amount: u64) -> Result<()> {
        // Guard: the authority account MUST match the admin recorded on the
        // config account. This is equivalent to a Signer constraint for this
        // code path because only admin's keypair satisfies it in production.
        require_keys_eq!(
            ctx.accounts.authority.key(),
            ctx.accounts.config.admin,
            ErrorCode::UnauthorizedAuthority
        );

        let vault = &mut ctx.accounts.vault;
        vault.balance = vault
            .balance
            .checked_sub(amount)
            .ok_or(ErrorCode::Underflow)?;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    pub config: Account<'info, Config>,
    // Looks suspicious in isolation, but gated via require_keys_eq! above.
    /// CHECK: validated against config.admin via require_keys_eq!
    pub authority: AccountInfo<'info>,
}

#[account]
pub struct Vault {
    pub balance: u64,
}

#[account]
pub struct Config {
    pub admin: Pubkey,
}

#[error_code]
pub enum ErrorCode {
    #[msg("Authority does not match config.admin")]
    UnauthorizedAuthority,
    #[msg("Underflow")]
    Underflow,
}
