// SPDX-License-Identifier: MIT
// Source: Adapted from coral-xyz/sealevel-attacks@24555d0
// (programs/2-owner-checks/insecure).
//
// Expected rule: missing_owner_check
// Expected severity: High
// Expected location: ~line 19-26 (AccountInfo deserialization without owner)
// Ground truth: 1 high finding
// Clean?: NO (has_vuln=true)

use anchor_lang::prelude::*;
use borsh::{BorshDeserialize, BorshSerialize};

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod owner_checks_insecure {
    use super::*;

    pub fn log_message(ctx: Context<LogMessage>) -> Result<()> {
        // VULN: vault is raw AccountInfo — no owner assertion. Attacker
        // can pass a lookalike account owned by a different program.
        let vault = &ctx.accounts.vault;
        let decoded = Vault::try_from_slice(&vault.data.borrow())?;
        if decoded.authority != ctx.accounts.authority.key() {
            return err!(ErrorCode::Unauthorized);
        }
        msg!("vault balance = {}", decoded.balance);
        Ok(())
    }
}

#[derive(Accounts)]
pub struct LogMessage<'info> {
    pub vault: AccountInfo<'info>,
    pub authority: Signer<'info>,
}

#[derive(BorshSerialize, BorshDeserialize)]
pub struct Vault {
    pub authority: Pubkey,
    pub balance: u64,
}

#[error_code]
pub enum ErrorCode {
    #[msg("Unauthorized")]
    Unauthorized,
}
