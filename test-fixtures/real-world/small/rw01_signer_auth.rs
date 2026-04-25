// SPDX-License-Identifier: MIT
// Source: Adapted from coral-xyz/sealevel-attacks@24555d0
// (programs/0-signer-authorization/insecure) — public educational corpus.
// Original describes the exact same "AccountInfo authority without signer
// check" pattern; this copy is simplified for SolGuard benchmarking.
//
// Expected rule: missing_signer_check
// Expected severity: High
// Expected location: ~line 22 (authority field) / ~line 14 (log_message)
// Ground truth: 1 high finding
// Clean?: NO (has_vuln=true)

use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod signer_authorization_insecure {
    use super::*;

    pub fn log_message(ctx: Context<LogMessage>) -> Result<()> {
        // VULN: authority is accepted as AccountInfo with no signer
        // assertion. Any caller can forge a message on behalf of the
        // claimed authority.
        msg!("GM {}", ctx.accounts.authority.key().to_string());
        Ok(())
    }
}

#[derive(Accounts)]
pub struct LogMessage<'info> {
    pub authority: AccountInfo<'info>,
}
