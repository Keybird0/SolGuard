// SPDX-License-Identifier: MIT
//! Test fixture: Arbitrary CPI
//!
//! Expected rule:   arbitrary_cpi
//! Expected severity: Critical
//! Expected location: line ~31 (`invoke_signed(&ix, &accounts_iter, ...)`).
//!
//! Root cause: the CPI target program id comes directly from
//! `ctx.accounts.target_program.key()` without any validation. An attacker
//! passes a malicious program that executes under our seeds.

use anchor_lang::prelude::*;
use solana_program::instruction::{AccountMeta, Instruction};
use solana_program::program::invoke_signed;

declare_id!("ArbCpi111111111111111111111111111111111111");

#[program]
pub mod arbitrary_cpi {
    use super::*;

    pub fn forward(ctx: Context<Forward>, data: Vec<u8>) -> Result<()> {
        let ix = Instruction {
            // BUG: program_id taken from user-supplied account without validation.
            program_id: *ctx.accounts.target_program.key,
            accounts: vec![AccountMeta::new(ctx.accounts.vault.key(), false)],
            data,
        };
        let seeds: &[&[u8]] = &[b"vault", &[ctx.bumps.vault]];
        invoke_signed(&ix, &[ctx.accounts.vault.to_account_info()], &[seeds])?;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Forward<'info> {
    /// CHECK: validated by seeds above.
    #[account(mut, seeds = [b"vault"], bump)]
    pub vault: AccountInfo<'info>,
    /// CHECK: intentionally unchecked for the test fixture.
    pub target_program: AccountInfo<'info>,
    pub authority: Signer<'info>,
}
