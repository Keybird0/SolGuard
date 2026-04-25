// SPDX-License-Identifier: MIT
// Source: Inspired by common Anchor vesting/streaming patterns
// (see Anchor Book §PDA + §CPI). Synthetic; no direct copy.
//
// Expected rule: (none)
// Expected severity: —
// Expected location: —
// Ground truth: 0 findings
// Clean?: YES (has_vuln=false)

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer};

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod clean_vesting {
    use super::*;

    pub fn create_stream(
        ctx: Context<CreateStream>,
        total: u64,
        start_ts: i64,
        duration_s: i64,
    ) -> Result<()> {
        require!(duration_s > 0, VestingError::InvalidDuration);
        let stream = &mut ctx.accounts.stream;
        stream.beneficiary = ctx.accounts.beneficiary.key();
        stream.mint = ctx.accounts.mint.key();
        stream.total = total;
        stream.released = 0;
        stream.start_ts = start_ts;
        stream.duration_s = duration_s;
        stream.bump = *ctx.bumps.get("stream").unwrap();

        let cpi_ctx = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.funder_token.to_account_info(),
                to: ctx.accounts.vault.to_account_info(),
                authority: ctx.accounts.funder.to_account_info(),
            },
        );
        token::transfer(cpi_ctx, total)
    }

    pub fn release(ctx: Context<Release>) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let stream = &mut ctx.accounts.stream;
        require_keys_eq!(stream.beneficiary, ctx.accounts.beneficiary.key(), VestingError::Unauthorized);
        require_keys_eq!(stream.mint, ctx.accounts.vault.mint, VestingError::MintMismatch);

        let elapsed = now.saturating_sub(stream.start_ts).max(0) as u64;
        let duration = stream.duration_s.max(1) as u64;
        let vested = if elapsed >= duration {
            stream.total
        } else {
            stream.total
                .checked_mul(elapsed)
                .and_then(|p| p.checked_div(duration))
                .ok_or(VestingError::Overflow)?
        };
        let releasable = vested.checked_sub(stream.released).ok_or(VestingError::Overflow)?;
        require!(releasable > 0, VestingError::NothingToRelease);

        let beneficiary_key = stream.beneficiary;
        let seeds = &[
            b"stream",
            beneficiary_key.as_ref(),
            &[stream.bump],
        ];
        let signer = &[&seeds[..]];
        let cpi_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.vault.to_account_info(),
                to: ctx.accounts.beneficiary_token.to_account_info(),
                authority: ctx.accounts.stream.to_account_info(),
            },
            signer,
        );
        token::transfer(cpi_ctx, releasable)?;
        stream.released = stream.released.checked_add(releasable).ok_or(VestingError::Overflow)?;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct CreateStream<'info> {
    #[account(
        init,
        payer = funder,
        space = 8 + 32 * 2 + 8 * 4 + 1,
        seeds = [b"stream", beneficiary.key().as_ref()],
        bump,
    )]
    pub stream: Account<'info, Stream>,
    pub mint: Account<'info, Mint>,
    #[account(mut)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub funder_token: Account<'info, TokenAccount>,
    /// CHECK: validated by `has_one` on Release path.
    pub beneficiary: AccountInfo<'info>,
    #[account(mut)]
    pub funder: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Release<'info> {
    #[account(
        mut,
        seeds = [b"stream", beneficiary.key().as_ref()],
        bump = stream.bump,
    )]
    pub stream: Account<'info, Stream>,
    #[account(mut)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub beneficiary_token: Account<'info, TokenAccount>,
    pub beneficiary: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[account]
pub struct Stream {
    pub beneficiary: Pubkey,
    pub mint: Pubkey,
    pub total: u64,
    pub released: u64,
    pub start_ts: i64,
    pub duration_s: i64,
    pub bump: u8,
}

#[error_code]
pub enum VestingError {
    #[msg("Invalid duration")]
    InvalidDuration,
    #[msg("Unauthorized")]
    Unauthorized,
    #[msg("Mint mismatch")]
    MintMismatch,
    #[msg("Arithmetic overflow")]
    Overflow,
    #[msg("Nothing to release")]
    NothingToRelease,
}
