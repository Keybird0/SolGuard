// SPDX-License-Identifier: MIT
//! Test fixture: Missing Owner Check
//!
//! Expected rule:   missing_owner_check
//! Expected severity: High
//! Expected location: line ~28 (`pub config: AccountInfo<'info>`).
//!
//! Root cause: `config` is deserialized manually from a raw `AccountInfo`
//! without validating ownership. An attacker can pass an attacker-owned
//! account whose bytes happen to deserialize into `Config`.

use anchor_lang::prelude::*;
use std::io::Cursor;

declare_id!("BPFLoaderUpgradeab1e11111111111111111111111");

#[program]
pub mod missing_owner {
    use super::*;

    pub fn update_config(ctx: Context<UpdateConfig>, new_fee: u64) -> Result<()> {
        let mut data = ctx.accounts.config.try_borrow_mut_data()?;
        // BUG: no owner check before deserialization.
        let mut cfg: Config = AnchorDeserialize::deserialize(&mut &data[..])?;
        cfg.fee_bps = new_fee;
        cfg.serialize(&mut Cursor::new(&mut data[..]))?;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct UpdateConfig<'info> {
    #[account(mut)]
    pub config: AccountInfo<'info>,
    pub admin: Signer<'info>,
}

#[derive(AnchorSerialize, AnchorDeserialize)]
pub struct Config {
    pub fee_bps: u64,
    pub treasury: Pubkey,
}
