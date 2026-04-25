// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { mkdtempSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { describe, it } from 'node:test';
import { PublicKey } from '@solana/web3.js';
import {
  normalizeContractAddress,
  looksLikeSolanaAddress,
} from './normalize-contract-address';

const VALID_ADDRESS = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA';
const TOKEN_PROGRAM_ID = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA';
const TOKEN_2022_PROGRAM_ID = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb';
const BPF_LOADER_UPGRADEABLE = 'BPFLoaderUpgradeab1e11111111111111111111111';

/** Build a fake 82-byte SPL Token Mint account body. */
function buildMintBuffer(opts: {
  mintAuthority: string | null;
  freezeAuthority: string | null;
  supply?: bigint;
  decimals?: number;
  extraTrailingBytes?: number; // for Token-2022 padding
}): Uint8Array {
  const baseSize = 82;
  const buf = Buffer.alloc(baseSize + (opts.extraTrailingBytes ?? 0));
  // Mint authority COption + key
  if (opts.mintAuthority) {
    buf.writeUInt32LE(1, 0);
    new PublicKey(opts.mintAuthority).toBuffer().copy(buf, 4);
  } else {
    buf.writeUInt32LE(0, 0);
  }
  buf.writeBigUInt64LE(opts.supply ?? 0n, 36);
  buf.writeUInt8(opts.decimals ?? 9, 44);
  buf.writeUInt8(1, 45); // is_initialized = true
  if (opts.freezeAuthority) {
    buf.writeUInt32LE(1, 46);
    new PublicKey(opts.freezeAuthority).toBuffer().copy(buf, 50);
  } else {
    buf.writeUInt32LE(0, 46);
  }
  return new Uint8Array(buf);
}

/** Build an UpgradeableLoader Program account (tag=2 + programdata pubkey). */
function buildUpgradeableProgramBuffer(programDataAddress: string): Uint8Array {
  const buf = Buffer.alloc(36);
  buf.writeUInt32LE(2, 0);
  new PublicKey(programDataAddress).toBuffer().copy(buf, 4);
  return new Uint8Array(buf);
}

/** Build an UpgradeableLoader ProgramData header (tag=3 + slot + auth COption). */
function buildProgramDataBuffer(opts: {
  upgradeAuthority: string | null;
  bytecodeBytes?: number;
}): Uint8Array {
  const headerSize = 45;
  const buf = Buffer.alloc(headerSize + (opts.bytecodeBytes ?? 4));
  buf.writeUInt32LE(3, 0); // ProgramData tag
  buf.writeBigUInt64LE(123n, 4); // slot
  if (opts.upgradeAuthority) {
    buf.writeUInt8(1, 12);
    new PublicKey(opts.upgradeAuthority).toBuffer().copy(buf, 13);
  } else {
    buf.writeUInt8(0, 12);
  }
  return new Uint8Array(buf);
}

describe('looksLikeSolanaAddress', () => {
  it('accepts a canonical base58 address', () => {
    assert.equal(looksLikeSolanaAddress(VALID_ADDRESS), true);
  });
  it('rejects 0x-prefixed hex', () => {
    assert.equal(looksLikeSolanaAddress('0xdeadbeef'), false);
  });
  it('rejects too-short tokens', () => {
    assert.equal(looksLikeSolanaAddress('abcdef'), false);
  });
});

describe('normalizeContractAddress', () => {
  it('fetches account info and writes bytecode', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-addr-'));
    const data = new Uint8Array([0x7f, 0x45, 0x4c, 0x46, 0x01, 0x02, 0x03, 0x04]);
    const res = await normalizeContractAddress(
      { type: 'contract_address', value: VALID_ADDRESS },
      workdir,
      {
        fetchAccountInfo: async () => ({
          data,
          owner: 'BPFLoaderUpgradeab1e11111111111111111111111',
          executable: true,
        }),
      },
    );

    assert.equal(res.kind, 'bytecode_only');
    if (res.kind === 'bytecode_only') {
      assert.equal(res.programId, VALID_ADDRESS);
      const actual = readFileSync(res.bytecodePath);
      assert.deepEqual(Array.from(actual), Array.from(data));
    }
  });

  it('throws when RPC returns null (account not found)', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-addr-'));
    await assert.rejects(
      normalizeContractAddress(
        { type: 'contract_address', value: VALID_ADDRESS },
        workdir,
        { fetchAccountInfo: async () => null },
      ),
      /account not found/,
    );
  });

  it('throws on invalid base58', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-addr-'));
    await assert.rejects(
      normalizeContractAddress(
        { type: 'contract_address', value: 'bad!address' },
        workdir,
        { fetchAccountInfo: async () => null },
      ),
      /not a valid base58/,
    );
  });
});

describe('normalizeContractAddress · onchain authority parsing', () => {
  const MINT_AUTH = 'So11111111111111111111111111111111111111112';
  const FREEZE_AUTH = '11111111111111111111111111111112';
  const UPGRADE_AUTH = '4Nd1mYRkqHtUuYQTRjNTdxN2cZBn2X2KHxZmQ7QBPnUk';

  it('parses an SPL Token mint with both authorities live (kind=mint, EOA risk)', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-addr-'));
    const data = buildMintBuffer({
      mintAuthority: MINT_AUTH,
      freezeAuthority: FREEZE_AUTH,
      supply: 1_000_000_000n,
    });
    const res = await normalizeContractAddress(
      { type: 'contract_address', value: VALID_ADDRESS },
      workdir,
      {
        fetchAccountInfo: async () => ({
          data,
          owner: TOKEN_PROGRAM_ID,
          executable: false,
        }),
      },
    );

    assert.equal(res.kind, 'bytecode_only');
    if (res.kind !== 'bytecode_only') return;
    assert.ok(res.onchain, 'onchain snapshot must be set');
    assert.equal(res.onchain.kind, 'mint');
    assert.equal(res.onchain.mintAuthority, MINT_AUTH);
    assert.equal(res.onchain.freezeAuthority, FREEZE_AUTH);
    assert.equal(res.onchain.upgradeAuthority, undefined);
  });

  it('parses an SPL Token-2022 mint with revoked authorities + extensions', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-addr-'));
    // Build a 165-byte padded base mint with both auths set to None,
    // followed by AccountType=1 (Mint) discriminator at offset 165, then
    // a TLV with type=12 (PermanentDelegate, length=32 placeholder).
    const baseMint = buildMintBuffer({
      mintAuthority: null,
      freezeAuthority: null,
      extraTrailingBytes: 165 - 82,
    });
    const tlv = Buffer.alloc(1 + 4 + 32); // 1 byte AccountType + 4 byte TLV header + 32 byte body
    tlv.writeUInt8(1, 0); // AccountType.Mint
    tlv.writeUInt16LE(12, 1); // type = PermanentDelegate
    tlv.writeUInt16LE(32, 3); // length = 32
    const data = Buffer.concat([Buffer.from(baseMint), tlv]);

    const res = await normalizeContractAddress(
      { type: 'contract_address', value: VALID_ADDRESS },
      workdir,
      {
        fetchAccountInfo: async () => ({
          data: new Uint8Array(data),
          owner: TOKEN_2022_PROGRAM_ID,
          executable: false,
        }),
      },
    );

    assert.equal(res.kind, 'bytecode_only');
    if (res.kind !== 'bytecode_only') return;
    assert.ok(res.onchain);
    assert.equal(res.onchain.kind, 'mint-2022');
    assert.equal(res.onchain.mintAuthority, null);
    assert.equal(res.onchain.freezeAuthority, null);
    assert.deepEqual(res.onchain.token2022Extensions, ['PermanentDelegate']);
  });

  it('chains a second RPC call to extract upgrade authority of an upgradeable program', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-addr-'));
    const programDataKey = 'BPFLoaderUpgradeab1e11111111111111111111111';
    const programData = buildUpgradeableProgramBuffer(programDataKey);
    const programDataAccountBytes = buildProgramDataBuffer({
      upgradeAuthority: UPGRADE_AUTH,
      bytecodeBytes: 12,
    });

    let calls = 0;
    const res = await normalizeContractAddress(
      { type: 'contract_address', value: VALID_ADDRESS },
      workdir,
      {
        fetchAccountInfo: async (id: string) => {
          calls += 1;
          if (calls === 1) {
            return {
              data: programData,
              owner: BPF_LOADER_UPGRADEABLE,
              executable: true,
            };
          }
          assert.equal(id, programDataKey);
          return {
            data: programDataAccountBytes,
            owner: BPF_LOADER_UPGRADEABLE,
            executable: false,
          };
        },
      },
    );

    assert.equal(calls, 2, 'should make exactly 2 RPC calls (program + programdata)');
    assert.equal(res.kind, 'bytecode_only');
    if (res.kind !== 'bytecode_only') return;
    assert.ok(res.onchain);
    assert.equal(res.onchain.kind, 'program-upgradeable');
    assert.equal(res.onchain.upgradeAuthority, UPGRADE_AUTH);
    assert.equal(res.onchain.executable, true);
  });
});
