// SPDX-License-Identifier: MIT
//! Test fixture: Missing Signer Check
//!
//! Expected rule:   missing_signer_check
//! Expected severity: High
//! Expected location: line ~22 (`pub authority: AccountInfo<'info>`).
//!
//! Root cause: the `authority` account is treated as the privileged caller
//! but never asserted to be a Signer. Any caller can spoof authority and
//! drain funds.

use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod missing_signer {
    use super::*;

    pub fn withdraw(ctx: Context<Withdraw>, amount: u64) -> Result<()> {
        let vault = &mut ctx.accounts.vault;
        vault.balance = vault.balance.saturating_sub(amount);
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    // BUG: this should be `Signer<'info>` or use `#[account(signer)]`.
    pub authority: AccountInfo<'info>,
}

#[account]
pub struct Vault {
    pub balance: u64,
}
