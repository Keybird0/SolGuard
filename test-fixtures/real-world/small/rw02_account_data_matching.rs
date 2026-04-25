// SPDX-License-Identifier: MIT
// Source: Adapted from coral-xyz/sealevel-attacks@24555d0
// (programs/1-account-data-matching/insecure).
//
// Expected rule: account_data_matching (or missing_signer_check)
// Expected severity: High
// Expected location: ~line 18-22 (log_message body)
// Ground truth: 1 high finding (account_data_matching)
// Clean?: NO (has_vuln=true)

use anchor_lang::prelude::*;
use anchor_spl::token::TokenAccount;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod account_data_matching_insecure {
    use super::*;

    pub fn log_message(ctx: Context<LogMessage>) -> Result<()> {
        // VULN: token.owner is never asserted against authority. An
        // attacker can pass any token account and the program will
        // happily log on behalf of an unrelated wallet.
        let token = &ctx.accounts.token;
        msg!("Owner: {}", token.owner);
        msg!("Amount: {}", token.amount);
        Ok(())
    }
}

#[derive(Accounts)]
pub struct LogMessage<'info> {
    pub token: Account<'info, TokenAccount>,
    pub authority: Signer<'info>,
}
