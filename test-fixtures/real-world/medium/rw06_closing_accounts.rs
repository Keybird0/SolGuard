// SPDX-License-Identifier: MIT
// Source: Adapted from coral-xyz/sealevel-attacks@24555d0
// (programs/9-closing-accounts/insecure). Expanded with two sibling
// instructions and a helper module to reach "medium" scale (~150 LoC).
//
// Expected rule: missing_owner_check + uninitialized_account
// Expected severity: High
// Expected location: ~line 42-68 (close handler manually zeroes lamports
//   without discriminator wipe)
// Ground truth: 2 findings (one High close-bug + one Medium uninit-on-reuse)
// Clean?: NO (has_vuln=true)

use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod closing_accounts_insecure {
    use super::*;

    /// Transfer tokens to `destination`. Normal-looking, but uses manual
    /// owner check so re-initialization after close is not forced.
    pub fn deposit(ctx: Context<Deposit>, amount: u64) -> Result<()> {
        let vault = &mut ctx.accounts.vault;
        if vault.owner != ctx.accounts.payer.key() {
            return err!(ErrorCode::Unauthorized);
        }
        vault.balance = vault.balance.checked_add(amount).ok_or(ErrorCode::Overflow)?;
        Ok(())
    }

    pub fn withdraw(ctx: Context<Withdraw>, amount: u64) -> Result<()> {
        let vault = &mut ctx.accounts.vault;
        require_keys_eq!(vault.owner, ctx.accounts.payer.key(), ErrorCode::Unauthorized);
        vault.balance = vault.balance.checked_sub(amount).ok_or(ErrorCode::Overflow)?;
        Ok(())
    }

    /// VULN: closes `vault` by draining lamports into `destination`
    /// without zeroing the discriminator, so the data stays readable
    /// by future instructions that re-reference the pubkey.
    pub fn close(ctx: Context<Close>) -> Result<()> {
        let vault_account_info = ctx.accounts.vault.to_account_info();
        let destination_account_info = ctx.accounts.destination.to_account_info();

        let dest_starting_lamports = destination_account_info.lamports();
        **destination_account_info.lamports.borrow_mut() = dest_starting_lamports
            .checked_add(vault_account_info.lamports())
            .unwrap();
        **vault_account_info.lamports.borrow_mut() = 0;

        // VULN (second): no data.zero() / discriminator wipe. If the
        // client re-funds rent in a later instruction, the stale
        // struct can be rehydrated.
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Deposit<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    pub payer: Signer<'info>,
}

#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    pub payer: Signer<'info>,
}

#[derive(Accounts)]
pub struct Close<'info> {
    #[account(mut)]
    pub vault: Account<'info, Vault>,
    #[account(mut)]
    /// CHECK: destination is an arbitrary lamport sink.
    pub destination: AccountInfo<'info>,
    pub payer: Signer<'info>,
}

#[account]
pub struct Vault {
    pub owner: Pubkey,
    pub balance: u64,
}

#[error_code]
pub enum ErrorCode {
    #[msg("Unauthorized")]
    Unauthorized,
    #[msg("Arithmetic overflow")]
    Overflow,
}
