// SPDX-License-Identifier: MIT
// Source: Synthetic AMM instruction slice inspired by public Solana AMM
// designs (Raydium, Orca Whirlpools, Meteora). Not copied from any
// specific audit target. Purpose: stress-test SolGuard on a multi-
// instruction, multi-account program with *mixed* safe/unsafe logic.
//
// Expected rules (multiple):
//   - integer_overflow @ swap() pre-fee multiply path      (Medium)
//   - missing_signer_check @ admin_set_fee() admin field   (High)
//   - arbitrary_cpi @ emergency_withdraw CPI               (Critical)
// Ground truth: 3 findings (1 Medium + 1 High + 1 Critical)
// Clean?: NO (has_vuln=true)

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer};
use solana_program::program::invoke;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

pub const FEE_DENOMINATOR: u64 = 10_000;

#[program]
pub mod amm_slice {
    use super::*;

    pub fn initialize_pool(
        ctx: Context<InitializePool>,
        fee_bps: u16,
    ) -> Result<()> {
        require!(fee_bps <= 1000, AmmError::FeeTooHigh);
        let pool = &mut ctx.accounts.pool;
        pool.token_a_mint = ctx.accounts.token_a_mint.key();
        pool.token_b_mint = ctx.accounts.token_b_mint.key();
        pool.token_a_vault = ctx.accounts.token_a_vault.key();
        pool.token_b_vault = ctx.accounts.token_b_vault.key();
        pool.lp_mint = ctx.accounts.lp_mint.key();
        pool.admin = ctx.accounts.admin.key();
        pool.fee_bps = fee_bps;
        pool.bump = *ctx.bumps.get("pool_authority").unwrap();
        pool.total_lp = 0;
        Ok(())
    }

    pub fn add_liquidity(
        ctx: Context<AddLiquidity>,
        amount_a: u64,
        amount_b: u64,
    ) -> Result<()> {
        require_keys_eq!(
            ctx.accounts.pool.token_a_mint,
            ctx.accounts.user_token_a.mint,
            AmmError::MintMismatch
        );
        require_keys_eq!(
            ctx.accounts.pool.token_b_mint,
            ctx.accounts.user_token_b.mint,
            AmmError::MintMismatch
        );

        // Deposit A
        let cpi_a = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_token_a.to_account_info(),
                to: ctx.accounts.token_a_vault.to_account_info(),
                authority: ctx.accounts.user.to_account_info(),
            },
        );
        token::transfer(cpi_a, amount_a)?;

        // Deposit B
        let cpi_b = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_token_b.to_account_info(),
                to: ctx.accounts.token_b_vault.to_account_info(),
                authority: ctx.accounts.user.to_account_info(),
            },
        );
        token::transfer(cpi_b, amount_b)?;

        let pool = &mut ctx.accounts.pool;
        let minted = (amount_a as u128)
            .checked_mul(amount_b as u128)
            .and_then(|p| Some((p as f64).sqrt() as u64))
            .ok_or(AmmError::Overflow)?;
        pool.total_lp = pool.total_lp.checked_add(minted).ok_or(AmmError::Overflow)?;
        Ok(())
    }

    pub fn swap(ctx: Context<Swap>, amount_in: u64, min_out: u64) -> Result<()> {
        let pool = &ctx.accounts.pool;

        // VULN (integer_overflow, Medium): pre-fee multiply uses u64
        // without checked_mul. For large reserves or large amount_in
        // this silently wraps.
        let fee = amount_in * pool.fee_bps as u64 / FEE_DENOMINATOR;
        let amount_in_after_fee = amount_in - fee;

        let reserve_in = ctx.accounts.reserve_in.amount;
        let reserve_out = ctx.accounts.reserve_out.amount;

        // Constant-product: out = reserve_out * amount_in_after_fee / (reserve_in + amount_in_after_fee)
        let numerator = (reserve_out as u128)
            .checked_mul(amount_in_after_fee as u128)
            .ok_or(AmmError::Overflow)?;
        let denominator = (reserve_in as u128)
            .checked_add(amount_in_after_fee as u128)
            .ok_or(AmmError::Overflow)?;
        let amount_out = (numerator
            .checked_div(denominator)
            .ok_or(AmmError::Overflow)?) as u64;
        require!(amount_out >= min_out, AmmError::SlippageExceeded);

        let pool_key = pool.key();
        let seeds = &[
            b"pool_authority",
            pool_key.as_ref(),
            &[pool.bump],
        ];
        let signer = &[&seeds[..]];

        // Pull in
        let cpi_in = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_in.to_account_info(),
                to: ctx.accounts.reserve_in.to_account_info(),
                authority: ctx.accounts.user.to_account_info(),
            },
        );
        token::transfer(cpi_in, amount_in)?;

        // Push out under PDA authority
        let cpi_out = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.reserve_out.to_account_info(),
                to: ctx.accounts.user_out.to_account_info(),
                authority: ctx.accounts.pool_authority.to_account_info(),
            },
            signer,
        );
        token::transfer(cpi_out, amount_out)
    }

    /// VULN (missing_signer_check, High): `admin` is an AccountInfo with
    /// no signer assertion; anyone who knows the admin pubkey can bump
    /// the fee. A proper implementation pins the admin to `Signer<'info>`
    /// and asserts `pool.admin == admin.key()`.
    pub fn admin_set_fee(ctx: Context<AdminSetFee>, new_fee_bps: u16) -> Result<()> {
        require!(new_fee_bps <= 1000, AmmError::FeeTooHigh);
        require_keys_eq!(
            ctx.accounts.pool.admin,
            ctx.accounts.admin.key(),
            AmmError::Unauthorized
        );
        ctx.accounts.pool.fee_bps = new_fee_bps;
        Ok(())
    }

    /// VULN (arbitrary_cpi, Critical): `token_program` is a raw
    /// AccountInfo that is passed straight into `invoke` with no address
    /// guard. An attacker swaps in a malicious program that returns
    /// "success" without moving funds.
    pub fn emergency_withdraw(ctx: Context<EmergencyWithdraw>, amount: u64) -> Result<()> {
        require_keys_eq!(
            ctx.accounts.pool.admin,
            ctx.accounts.admin.key(),
            AmmError::Unauthorized
        );

        let ix = spl_token::instruction::transfer(
            ctx.accounts.token_program.key,
            ctx.accounts.vault.key,
            ctx.accounts.destination.key,
            ctx.accounts.pool_authority.key,
            &[],
            amount,
        )?;
        invoke(
            &ix,
            &[
                ctx.accounts.vault.clone(),
                ctx.accounts.destination.clone(),
                ctx.accounts.pool_authority.clone(),
            ],
        )?;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct InitializePool<'info> {
    #[account(init, payer = admin, space = 8 + 32 * 6 + 2 + 1 + 8)]
    pub pool: Account<'info, Pool>,
    pub token_a_mint: Account<'info, Mint>,
    pub token_b_mint: Account<'info, Mint>,
    #[account(mut)]
    pub token_a_vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub token_b_vault: Account<'info, TokenAccount>,
    pub lp_mint: Account<'info, Mint>,
    /// CHECK: PDA authority
    #[account(seeds = [b"pool_authority", pool.key().as_ref()], bump)]
    pub pool_authority: AccountInfo<'info>,
    #[account(mut)]
    pub admin: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct AddLiquidity<'info> {
    #[account(mut)]
    pub pool: Account<'info, Pool>,
    #[account(mut)]
    pub user_token_a: Account<'info, TokenAccount>,
    #[account(mut)]
    pub user_token_b: Account<'info, TokenAccount>,
    #[account(mut, address = pool.token_a_vault)]
    pub token_a_vault: Account<'info, TokenAccount>,
    #[account(mut, address = pool.token_b_vault)]
    pub token_b_vault: Account<'info, TokenAccount>,
    pub user: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct Swap<'info> {
    pub pool: Account<'info, Pool>,
    #[account(mut)]
    pub reserve_in: Account<'info, TokenAccount>,
    #[account(mut)]
    pub reserve_out: Account<'info, TokenAccount>,
    #[account(mut)]
    pub user_in: Account<'info, TokenAccount>,
    #[account(mut)]
    pub user_out: Account<'info, TokenAccount>,
    /// CHECK: PDA authority
    #[account(seeds = [b"pool_authority", pool.key().as_ref()], bump = pool.bump)]
    pub pool_authority: AccountInfo<'info>,
    pub user: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct AdminSetFee<'info> {
    #[account(mut)]
    pub pool: Account<'info, Pool>,
    /// CHECK: VULN — should be Signer<'info>
    pub admin: AccountInfo<'info>,
}

#[derive(Accounts)]
pub struct EmergencyWithdraw<'info> {
    pub pool: Account<'info, Pool>,
    #[account(mut)]
    /// CHECK: token vault
    pub vault: AccountInfo<'info>,
    #[account(mut)]
    /// CHECK: destination
    pub destination: AccountInfo<'info>,
    /// CHECK: PDA authority
    #[account(seeds = [b"pool_authority", pool.key().as_ref()], bump = pool.bump)]
    pub pool_authority: AccountInfo<'info>,
    /// CHECK: VULN — raw AccountInfo, not Program<'info, Token>
    pub token_program: AccountInfo<'info>,
    pub admin: Signer<'info>,
}

#[account]
pub struct Pool {
    pub token_a_mint: Pubkey,
    pub token_b_mint: Pubkey,
    pub token_a_vault: Pubkey,
    pub token_b_vault: Pubkey,
    pub lp_mint: Pubkey,
    pub admin: Pubkey,
    pub fee_bps: u16,
    pub bump: u8,
    pub total_lp: u64,
}

#[error_code]
pub enum AmmError {
    #[msg("Fee too high")]
    FeeTooHigh,
    #[msg("Mint mismatch")]
    MintMismatch,
    #[msg("Arithmetic overflow")]
    Overflow,
    #[msg("Slippage exceeded")]
    SlippageExceeded,
    #[msg("Unauthorized")]
    Unauthorized,
}
