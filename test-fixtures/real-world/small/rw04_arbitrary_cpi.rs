// SPDX-License-Identifier: MIT
// Source: Adapted from coral-xyz/sealevel-attacks@24555d0
// (programs/5-arbitrary-cpi/insecure).
//
// Expected rule: arbitrary_cpi
// Expected severity: Critical
// Expected location: ~line 22-30 (invoke with untrusted token_program)
// Ground truth: 1 critical finding
// Clean?: NO (has_vuln=true)

use anchor_lang::prelude::*;
use solana_program::program::invoke;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod arbitrary_cpi_insecure {
    use super::*;

    pub fn cpi(ctx: Context<Cpi>, amount: u64) -> Result<()> {
        // VULN: token_program is an arbitrary AccountInfo with no
        // address assertion against anchor_spl::token::ID. An attacker
        // can point it at a malicious program that overrides
        // `transfer_checked`.
        let ix = spl_token::instruction::transfer(
            ctx.accounts.token_program.key,
            ctx.accounts.source.key,
            ctx.accounts.destination.key,
            ctx.accounts.authority.key,
            &[],
            amount,
        )?;
        invoke(
            &ix,
            &[
                ctx.accounts.source.clone(),
                ctx.accounts.destination.clone(),
                ctx.accounts.authority.clone(),
            ],
        )?;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Cpi<'info> {
    pub token_program: AccountInfo<'info>,
    pub source: AccountInfo<'info>,
    pub destination: AccountInfo<'info>,
    pub authority: Signer<'info>,
}
