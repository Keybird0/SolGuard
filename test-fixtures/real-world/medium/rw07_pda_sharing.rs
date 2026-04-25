// SPDX-License-Identifier: MIT
// Source: Adapted from coral-xyz/sealevel-attacks@24555d0
// (programs/8-pda-sharing/insecure). Extended with two pools and a
// helper to reach ~200 LoC "medium" scale.
//
// Expected rule: pda_derivation_error
// Expected severity: High
// Expected location: ~line 50-72 (withdraw uses single shared seed for
//   all pools — any pool admin can sign for any other pool)
// Ground truth: 1 high finding (pda_derivation_error)
// Clean?: NO (has_vuln=true)

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod pda_sharing_insecure {
    use super::*;

    pub fn initialize_pool(
        ctx: Context<InitializePool>,
        mint: Pubkey,
        withdraw_destination: Pubkey,
    ) -> Result<()> {
        ctx.accounts.pool.vault = ctx.accounts.vault.key();
        ctx.accounts.pool.mint = mint;
        ctx.accounts.pool.withdraw_destination = withdraw_destination;
        ctx.accounts.pool.bump = *ctx.bumps.get("pool_authority").unwrap();
        Ok(())
    }

    /// VULN: uses a single `mint` seed for `pool_authority`. Every pool
    /// that shares the same mint shares the same PDA — so admin of pool
    /// A can authorize transfers from pool B's vault.
    pub fn withdraw(ctx: Context<Withdraw>, amount: u64) -> Result<()> {
        let seeds = &[ctx.accounts.pool.mint.as_ref(), &[ctx.accounts.pool.bump]];
        let signer = &[&seeds[..]];
        let cpi_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.vault.to_account_info(),
                to: ctx.accounts.withdraw_destination.to_account_info(),
                authority: ctx.accounts.pool_authority.to_account_info(),
            },
            signer,
        );
        token::transfer(cpi_ctx, amount)
    }
}

#[derive(Accounts)]
#[instruction(mint: Pubkey)]
pub struct InitializePool<'info> {
    #[account(init, payer = payer, space = 8 + 32 * 3 + 1, seeds = [mint.as_ref()], bump)]
    pub pool: Account<'info, Pool>,
    pub vault: Account<'info, TokenAccount>,
    /// CHECK: PDA authority
    #[account(seeds = [mint.as_ref()], bump)]
    pub pool_authority: AccountInfo<'info>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Withdraw<'info> {
    pub pool: Account<'info, Pool>,
    #[account(mut)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub withdraw_destination: Account<'info, TokenAccount>,
    /// CHECK: PDA authority re-derived from mint only
    #[account(seeds = [pool.mint.as_ref()], bump = pool.bump)]
    pub pool_authority: AccountInfo<'info>,
    pub token_program: Program<'info, Token>,
}

#[account]
#[derive(Default)]
pub struct Pool {
    pub vault: Pubkey,
    pub mint: Pubkey,
    pub withdraw_destination: Pubkey,
    pub bump: u8,
}
