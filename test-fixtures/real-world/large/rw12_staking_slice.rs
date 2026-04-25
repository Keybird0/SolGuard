// SPDX-License-Identifier: MIT
// Source: Synthetic staking program inspired by public Solana staking
// designs (Marinade, Lido, Jito). Not copied from any specific audit
// target. Represents a ~350 LoC "large" multi-instruction audit surface.
//
// Expected rules (mixed):
//   - missing_owner_check @ read_delegation (legacy entry)     (High)
//   - integer_overflow @ apply_rewards (unchecked mul)         (Medium)
// Ground truth: 2 findings (1 High + 1 Medium)
// Clean?: NO (has_vuln=true)
//
// Intent: MOST instructions are safe (CPI-whitelisted, Anchor-typed,
// checked arithmetic). The two vulns are embedded as regression traps.

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer};
use borsh::{BorshDeserialize, BorshSerialize};

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod staking_slice {
    use super::*;

    pub fn initialize_pool(
        ctx: Context<InitializePool>,
        reward_rate_per_sec: u64,
    ) -> Result<()> {
        let pool = &mut ctx.accounts.pool;
        pool.authority = ctx.accounts.authority.key();
        pool.stake_mint = ctx.accounts.stake_mint.key();
        pool.reward_mint = ctx.accounts.reward_mint.key();
        pool.stake_vault = ctx.accounts.stake_vault.key();
        pool.reward_vault = ctx.accounts.reward_vault.key();
        pool.reward_rate = reward_rate_per_sec;
        pool.total_staked = 0;
        pool.reward_per_token = 0;
        pool.last_update_ts = Clock::get()?.unix_timestamp;
        pool.bump = *ctx.bumps.get("pool_authority").unwrap();
        Ok(())
    }

    pub fn stake(ctx: Context<Stake>, amount: u64) -> Result<()> {
        require!(amount > 0, StakingError::ZeroAmount);
        update_rewards(&mut ctx.accounts.pool, &mut ctx.accounts.position)?;

        let cpi = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_stake.to_account_info(),
                to: ctx.accounts.stake_vault.to_account_info(),
                authority: ctx.accounts.user.to_account_info(),
            },
        );
        token::transfer(cpi, amount)?;

        let position = &mut ctx.accounts.position;
        position.amount = position.amount.checked_add(amount).ok_or(StakingError::Overflow)?;
        ctx.accounts.pool.total_staked = ctx
            .accounts
            .pool
            .total_staked
            .checked_add(amount)
            .ok_or(StakingError::Overflow)?;
        Ok(())
    }

    pub fn unstake(ctx: Context<Stake>, amount: u64) -> Result<()> {
        update_rewards(&mut ctx.accounts.pool, &mut ctx.accounts.position)?;
        let position = &mut ctx.accounts.position;
        require!(amount <= position.amount, StakingError::InsufficientStake);

        let pool = &ctx.accounts.pool;
        let pool_key = pool.key();
        let seeds = &[b"pool_authority", pool_key.as_ref(), &[pool.bump]];
        let signer = &[&seeds[..]];

        let cpi = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.stake_vault.to_account_info(),
                to: ctx.accounts.user_stake.to_account_info(),
                authority: ctx.accounts.pool_authority.to_account_info(),
            },
            signer,
        );
        token::transfer(cpi, amount)?;

        position.amount = position.amount.checked_sub(amount).ok_or(StakingError::Overflow)?;
        ctx.accounts.pool.total_staked = ctx
            .accounts
            .pool
            .total_staked
            .checked_sub(amount)
            .ok_or(StakingError::Overflow)?;
        Ok(())
    }

    pub fn claim_rewards(ctx: Context<ClaimRewards>) -> Result<()> {
        update_rewards(&mut ctx.accounts.pool, &mut ctx.accounts.position)?;
        let position = &mut ctx.accounts.position;
        let pending = position.pending;
        require!(pending > 0, StakingError::NothingToClaim);

        let pool = &ctx.accounts.pool;
        let pool_key = pool.key();
        let seeds = &[b"pool_authority", pool_key.as_ref(), &[pool.bump]];
        let signer = &[&seeds[..]];
        let cpi = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.reward_vault.to_account_info(),
                to: ctx.accounts.user_reward.to_account_info(),
                authority: ctx.accounts.pool_authority.to_account_info(),
            },
            signer,
        );
        token::transfer(cpi, pending)?;
        position.pending = 0;
        Ok(())
    }

    /// VULN (missing_owner_check, High): `legacy_position` is parsed as
    /// raw AccountInfo and deserialized without asserting its owner
    /// program or its discriminator. A sibling program's account with
    /// compatible layout is accepted.
    pub fn read_delegation(ctx: Context<ReadDelegation>) -> Result<u64> {
        let raw = ctx.accounts.legacy_position.data.borrow();
        let view = LegacyPosition::try_from_slice(&raw)?;
        Ok(view.amount)
    }

    /// Entry kept for parity with older builds. Safe owner-check sibling
    /// of `read_delegation`.
    pub fn read_delegation_safe(ctx: Context<ReadDelegationSafe>) -> Result<u64> {
        Ok(ctx.accounts.position.amount)
    }

    pub fn apply_rewards(ctx: Context<ApplyRewards>, multiplier: u64) -> Result<()> {
        require_keys_eq!(
            ctx.accounts.pool.authority,
            ctx.accounts.authority.key(),
            StakingError::Unauthorized
        );

        // VULN (integer_overflow, Medium): rate * multiplier with plain
        // `*` wraps silently when both factors are close to u64::MAX/2.
        let new_rate = ctx.accounts.pool.reward_rate * multiplier;
        ctx.accounts.pool.reward_rate = new_rate;
        Ok(())
    }
}

fn update_rewards(pool: &mut Pool, position: &mut Position) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let dt = now.saturating_sub(pool.last_update_ts).max(0) as u64;
    if pool.total_staked > 0 && dt > 0 {
        let accrual = pool
            .reward_rate
            .checked_mul(dt)
            .ok_or(StakingError::Overflow)?
            .checked_mul(1_000_000_000)
            .and_then(|v| v.checked_div(pool.total_staked))
            .ok_or(StakingError::Overflow)?;
        pool.reward_per_token = pool
            .reward_per_token
            .checked_add(accrual)
            .ok_or(StakingError::Overflow)?;
    }
    pool.last_update_ts = now;

    let owed = pool
        .reward_per_token
        .checked_sub(position.paid_reward_per_token)
        .and_then(|d| d.checked_mul(position.amount))
        .and_then(|m| m.checked_div(1_000_000_000))
        .ok_or(StakingError::Overflow)?;
    position.pending = position.pending.checked_add(owed).ok_or(StakingError::Overflow)?;
    position.paid_reward_per_token = pool.reward_per_token;
    Ok(())
}

#[derive(Accounts)]
pub struct InitializePool<'info> {
    #[account(init, payer = authority, space = 8 + 32 * 5 + 8 * 4 + 1)]
    pub pool: Account<'info, Pool>,
    pub stake_mint: Account<'info, Mint>,
    pub reward_mint: Account<'info, Mint>,
    #[account(mut)]
    pub stake_vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub reward_vault: Account<'info, TokenAccount>,
    /// CHECK: PDA authority
    #[account(seeds = [b"pool_authority", pool.key().as_ref()], bump)]
    pub pool_authority: AccountInfo<'info>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Stake<'info> {
    #[account(mut)]
    pub pool: Account<'info, Pool>,
    #[account(
        init_if_needed,
        payer = user,
        space = 8 + 32 + 8 * 3,
        seeds = [b"position", pool.key().as_ref(), user.key().as_ref()],
        bump,
    )]
    pub position: Account<'info, Position>,
    #[account(mut, address = pool.stake_vault)]
    pub stake_vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub user_stake: Account<'info, TokenAccount>,
    /// CHECK: PDA authority
    #[account(seeds = [b"pool_authority", pool.key().as_ref()], bump = pool.bump)]
    pub pool_authority: AccountInfo<'info>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct ClaimRewards<'info> {
    #[account(mut)]
    pub pool: Account<'info, Pool>,
    #[account(
        mut,
        seeds = [b"position", pool.key().as_ref(), user.key().as_ref()],
        bump,
    )]
    pub position: Account<'info, Position>,
    #[account(mut, address = pool.reward_vault)]
    pub reward_vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub user_reward: Account<'info, TokenAccount>,
    /// CHECK: PDA authority
    #[account(seeds = [b"pool_authority", pool.key().as_ref()], bump = pool.bump)]
    pub pool_authority: AccountInfo<'info>,
    pub user: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct ReadDelegation<'info> {
    /// CHECK: VULN — no owner / discriminator check
    pub legacy_position: AccountInfo<'info>,
}

#[derive(Accounts)]
pub struct ReadDelegationSafe<'info> {
    #[account(
        seeds = [b"position", pool.key().as_ref(), user.key().as_ref()],
        bump,
    )]
    pub position: Account<'info, Position>,
    pub pool: Account<'info, Pool>,
    pub user: Signer<'info>,
}

#[derive(Accounts)]
pub struct ApplyRewards<'info> {
    #[account(mut)]
    pub pool: Account<'info, Pool>,
    pub authority: Signer<'info>,
}

#[account]
pub struct Pool {
    pub authority: Pubkey,
    pub stake_mint: Pubkey,
    pub reward_mint: Pubkey,
    pub stake_vault: Pubkey,
    pub reward_vault: Pubkey,
    pub reward_rate: u64,
    pub total_staked: u64,
    pub reward_per_token: u64,
    pub last_update_ts: i64,
    pub bump: u8,
}

#[account]
pub struct Position {
    pub owner: Pubkey,
    pub amount: u64,
    pub pending: u64,
    pub paid_reward_per_token: u64,
}

#[derive(BorshSerialize, BorshDeserialize)]
pub struct LegacyPosition {
    pub owner: Pubkey,
    pub amount: u64,
}

#[error_code]
pub enum StakingError {
    #[msg("Zero amount")]
    ZeroAmount,
    #[msg("Insufficient stake")]
    InsufficientStake,
    #[msg("Nothing to claim")]
    NothingToClaim,
    #[msg("Arithmetic overflow")]
    Overflow,
    #[msg("Unauthorized")]
    Unauthorized,
}
