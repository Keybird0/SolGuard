// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { mkdtempSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { describe, it } from 'node:test';
import {
  normalizeContractAddress,
  looksLikeSolanaAddress,
} from './normalize-contract-address';

const VALID_ADDRESS = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA';

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
