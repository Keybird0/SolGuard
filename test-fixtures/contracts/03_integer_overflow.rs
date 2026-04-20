// SPDX-License-Identifier: MIT
//! Test fixture: Integer Overflow
//!
//! Expected rule:   integer_overflow
//! Expected severity: Medium
//! Expected locations: lines ~22, ~28 (`+` and `-` on `u64` balances).
//!
//! Root cause: arithmetic uses unchecked `+`/`-` on `u64` balances.
//! Anchor release builds do NOT enable overflow-checks by default, so
//! wrap-around silently succeeds.

use anchor_lang::prelude::*;

declare_id!("Token1111111111111111111111111111111111111");

#[program]
pub mod overflow_demo {
    use super::*;

    pub fn deposit(ctx: Context<Tx>, amount: u64) -> Result<()> {
        let vault = &mut ctx.accounts.vault;
        // BUG: raw `+` can overflow.
        vault.balance = vault.balance + amount;
        Ok(())
    }

    pub fn withdraw(ctx: Context<Tx>, amount: u64) -> Result<()> {
        let vault = &mut ctx.accounts.vault;
        // BUG: raw `-` can underflow.
        vault.balance = vault.balance - amount;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Tx<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    pub authority: Signer<'info>,
}

#[account]
pub struct Vault {
    pub balance: u64,
}
