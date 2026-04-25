// SPDX-License-Identifier: MIT
// Source: Inspired by coral-xyz/anchor/examples/tutorial/basic-4 +
// Anchor Book "Escrow" example. Cleaned up to serve as a NEGATIVE
// (clean, no-vuln) benchmark fixture.
//
// Expected rule: (none)
// Expected severity: —
// Expected location: —
// Ground truth: 0 findings
// Clean?: YES (has_vuln=false)

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod clean_escrow {
    use super::*;

    pub fn initialize(
        ctx: Context<Initialize>,
        amount: u64,
        price: u64,
    ) -> Result<()> {
        let escrow = &mut ctx.accounts.escrow;
        escrow.seller = ctx.accounts.seller.key();
        escrow.amount = amount;
        escrow.price = price;
        escrow.bump = *ctx.bumps.get("escrow").unwrap();

        // Use Anchor's Transfer CPI with a whitelisted token_program.
        let cpi_ctx = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.seller_token.to_account_info(),
                to: ctx.accounts.vault.to_account_info(),
                authority: ctx.accounts.seller.to_account_info(),
            },
        );
        token::transfer(cpi_ctx, amount)
    }

    pub fn accept(ctx: Context<Accept>) -> Result<()> {
        let escrow = &ctx.accounts.escrow;
        let seeds = &[
            b"escrow".as_ref(),
            escrow.seller.as_ref(),
            &[escrow.bump],
        ];
        let signer = &[&seeds[..]];

        // Pay seller
        let payment_ctx = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.buyer_token.to_account_info(),
                to: ctx.accounts.seller_token.to_account_info(),
                authority: ctx.accounts.buyer.to_account_info(),
            },
        );
        token::transfer(payment_ctx, escrow.price)?;

        // Release vault -> buyer under PDA authority
        let release_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.vault.to_account_info(),
                to: ctx.accounts.buyer_token.to_account_info(),
                authority: ctx.accounts.escrow.to_account_info(),
            },
            signer,
        );
        token::transfer(release_ctx, escrow.amount)
    }

    pub fn cancel(ctx: Context<Cancel>) -> Result<()> {
        let escrow = &ctx.accounts.escrow;
        require_keys_eq!(escrow.seller, ctx.accounts.seller.key(), EscrowError::Unauthorized);
        let seeds = &[
            b"escrow".as_ref(),
            escrow.seller.as_ref(),
            &[escrow.bump],
        ];
        let signer = &[&seeds[..]];
        let refund_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.vault.to_account_info(),
                to: ctx.accounts.seller_token.to_account_info(),
                authority: ctx.accounts.escrow.to_account_info(),
            },
            signer,
        );
        token::transfer(refund_ctx, escrow.amount)
    }
}

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(
        init,
        payer = seller,
        space = 8 + 32 + 8 + 8 + 1,
        seeds = [b"escrow", seller.key().as_ref()],
        bump
    )]
    pub escrow: Account<'info, Escrow>,
    #[account(mut)]
    pub seller_token: Account<'info, TokenAccount>,
    #[account(mut)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub seller: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Accept<'info> {
    #[account(
        mut,
        seeds = [b"escrow", escrow.seller.as_ref()],
        bump = escrow.bump,
        close = seller,
    )]
    pub escrow: Account<'info, Escrow>,
    #[account(mut)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub buyer_token: Account<'info, TokenAccount>,
    #[account(mut)]
    pub seller_token: Account<'info, TokenAccount>,
    #[account(mut)]
    pub buyer: Signer<'info>,
    /// CHECK: validated via `escrow.seller` on close.
    #[account(mut, address = escrow.seller)]
    pub seller: AccountInfo<'info>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct Cancel<'info> {
    #[account(
        mut,
        seeds = [b"escrow", seller.key().as_ref()],
        bump = escrow.bump,
        close = seller,
    )]
    pub escrow: Account<'info, Escrow>,
    #[account(mut)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub seller_token: Account<'info, TokenAccount>,
    #[account(mut)]
    pub seller: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[account]
pub struct Escrow {
    pub seller: Pubkey,
    pub amount: u64,
    pub price: u64,
    pub bump: u8,
}

#[error_code]
pub enum EscrowError {
    #[msg("Unauthorized")]
    Unauthorized,
}
