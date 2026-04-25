// SPDX-License-Identifier: MIT
// Source: Adapted from coral-xyz/sealevel-attacks@24555d0
// (programs/7-bump-seed-canonicalization/insecure).
//
// Expected rule: pda_derivation_error
// Expected severity: High
// Expected location: ~line 20-28 (create_program_address without canonical bump)
// Ground truth: 1 high finding
// Clean?: NO (has_vuln=true)

use anchor_lang::prelude::*;
use solana_program::pubkey::Pubkey;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod bump_seed_canonicalization_insecure {
    use super::*;

    pub fn set_value(ctx: Context<BumpSeed>, key: u64, new_value: u64, bump: u8) -> Result<()> {
        // VULN: uses create_program_address with user-supplied `bump`
        // instead of find_program_address's canonical bump. Attacker
        // can grind alternate bumps that derive to *different* valid
        // addresses, enabling per-key shadow accounts.
        let address =
            Pubkey::create_program_address(&[key.to_le_bytes().as_ref(), &[bump]], ctx.program_id)?;
        if address != ctx.accounts.data.key() {
            return err!(ErrorCode::InvalidAddress);
        }
        ctx.accounts.data.value = new_value;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct BumpSeed<'info> {
    #[account(mut)]
    pub data: Account<'info, Data>,
    pub payer: Signer<'info>,
}

#[account]
pub struct Data {
    pub value: u64,
}

#[error_code]
pub enum ErrorCode {
    #[msg("Invalid address")]
    InvalidAddress,
}
