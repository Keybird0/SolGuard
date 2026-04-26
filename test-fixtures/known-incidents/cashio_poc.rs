// SPDX-License-Identifier: MIT
//! Cashio infinite-mint PoC — simplified single-file reproduction of the
//! root cause behind the 2022-03 Cashio exploit (~$52M loss).
//!
//! Real-world reference:
//!   - Post-mortem: https://medium.com/@cashioapp/cashio-march-23-attack-post-mortem
//!   - Root cause: a chain of `crate_collateral_tokens` accounts was followed
//!     **without verifying owner / discriminator** at each hop. The attacker
//!     supplied a fake `crate_collateral_tokens` account whose deserialised
//!     fields pointed at attacker-controlled state, letting them mint
//!     unbacked CASH stablecoin to themselves.
//!
//! Expected SolGuard hits:
//!   * R2 missing_owner_check on `print_with_collateral::collateral_tokens`
//!   * R5 account_data_matching on the manual `try_from_slice` of the
//!     same account
//!
//! Expected severity: High → upgraded to Critical by Gate3 attack ROI.
//!
//! This file is a single-file teaching reproduction; it is NOT the real
//! Cashio source and does not compile under cargo (no Cargo.toml). The
//! scanner reads it as text only.

use anchor_lang::prelude::*;
use anchor_lang::solana_program::program_pack::Pack;

declare_id!("CASHi0Mint1111111111111111111111111111111");

#[program]
pub mod cashio_minimal {
    use super::*;

    /// Mint CASH stablecoin against deposited LP collateral.
    /// VULNERABLE: `collateral_tokens` is a raw AccountInfo; we trust the
    /// `mint` field stored inside it without checking the account's
    /// owner program or its 8-byte Anchor discriminator.
    pub fn print_with_collateral(
        ctx: Context<PrintWithCollateral>,
        amount: u64,
    ) -> Result<()> {
        let collateral = &ctx.accounts.collateral_tokens;

        // BAD — manual deserialise on raw AccountInfo. No owner check.
        // Attacker supplies any account whose first 32 bytes happen to
        // decode as a Pubkey; that pubkey then drives `cash_mint`.
        let parsed = CollateralTokens::try_from_slice(
            &collateral.try_borrow_data()?,
        )?;

        // Attacker-controlled `parsed.cash_mint` ⇒ attacker mints to self.
        let cpi_accounts = anchor_spl::token::MintTo {
            mint: ctx.accounts.cash_mint.to_account_info(),
            to: ctx.accounts.attacker_destination.to_account_info(),
            authority: ctx.accounts.cash_mint_authority.to_account_info(),
        };
        let cpi_ctx = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            cpi_accounts,
        );

        // No checked_mul on the freshly-deserialised fake amount.
        let mintable = parsed.weight * amount;
        anchor_spl::token::mint_to(cpi_ctx, mintable)?;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct PrintWithCollateral<'info> {
    /// CHECK: vulnerable — no owner/discriminator constraints.
    #[account(mut)]
    pub collateral_tokens: AccountInfo<'info>,

    #[account(mut)]
    pub cash_mint: AccountInfo<'info>,

    #[account(mut)]
    pub attacker_destination: AccountInfo<'info>,

    /// CHECK: signer-only, no further constraints (PDA derivation is
    /// done elsewhere — out of scope for this slice).
    pub cash_mint_authority: AccountInfo<'info>,

    pub token_program: AccountInfo<'info>,

    pub user: Signer<'info>,
}

#[derive(borsh::BorshDeserialize, borsh::BorshSerialize)]
pub struct CollateralTokens {
    pub crate_token: Pubkey,
    pub cash_mint: Pubkey,
    pub weight: u64,
}
