// SPDX-License-Identifier: MIT
//! Adversarial fixture: condensed arbitrary-CPI kill signal.
//!
//! Variant of fixture 04 with the exploit path made more obvious: the
//! function explicitly signs with the program's vault PDA seeds while
//! dispatching to an attacker-controlled `target_program`. The AI is
//! expected to confirm `arbitrary_cpi` as a kill signal (severity=Critical).

use anchor_lang::prelude::*;
use solana_program::instruction::{AccountMeta, Instruction};
use solana_program::program::invoke_signed;

declare_id!("RealCpi1111111111111111111111111111111111");

#[program]
pub mod real_arbitrary_cpi {
    use super::*;

    pub fn forward_all(ctx: Context<Forward>, payload: Vec<u8>) -> Result<()> {
        // BUG #1: program_id is read straight from an unvalidated account.
        let ix = Instruction {
            program_id: *ctx.accounts.target_program.key,
            accounts: vec![
                AccountMeta::new(ctx.accounts.vault.key(), false),
                AccountMeta::new_readonly(ctx.accounts.target_program.key(), false),
            ],
            data: payload,
        };
        // BUG #2: we sign with OUR vault PDA seeds, delegating full
        // spending power to whatever program the attacker passes in.
        let seeds: &[&[u8]] = &[b"vault", &[ctx.bumps.vault]];
        invoke_signed(
            &ix,
            &[
                ctx.accounts.vault.to_account_info(),
                ctx.accounts.target_program.to_account_info(),
            ],
            &[seeds],
        )?;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Forward<'info> {
    #[account(mut, seeds = [b"vault"], bump)]
    /// CHECK: PDA, validated by seeds above.
    pub vault: AccountInfo<'info>,
    /// CHECK: intentionally unvalidated — that's the exploit.
    pub target_program: AccountInfo<'info>,
    pub authority: Signer<'info>,
}
