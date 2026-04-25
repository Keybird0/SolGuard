// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { config } from '../config';
import { logger } from '../logger';
import type { AuditInput, NormalizedInput, OnchainAuthority } from '../types';

/**
 * A minimal shape subset we need from Solana's `getAccountInfo` response.
 * We deliberately avoid depending on @solana/web3.js types here so the
 * unit tests don't need to instantiate a real Connection. The production
 * fetcher (`defaultFetchAccountInfo`) wraps @solana/web3.js internally.
 */
export interface RpcAccountInfo {
  data: Uint8Array;
  owner: string;
  executable: boolean;
}

export interface AddressNormalizerDeps {
  /** Override for unit tests / degraded RPC; default uses @solana/web3.js. */
  fetchAccountInfo?: (programId: string) => Promise<RpcAccountInfo | null>;
  rpcUrl?: string;
  timeoutMs?: number;
}

const BASE58_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

// Owner program IDs we recognise. Keep these as string literals (not
// PublicKey instances) so we don't pay the @solana/web3.js import cost in
// pure unit tests.
const TOKEN_PROGRAM_ID = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA';
const TOKEN_2022_PROGRAM_ID = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb';
const BPF_LOADER_UPGRADEABLE = 'BPFLoaderUpgradeab1e11111111111111111111111';
const BPF_LOADER_2 = 'BPFLoader2111111111111111111111111111111111';
const BPF_LOADER_LEGACY = 'BPFLoader1111111111111111111111111111111111';

// Token-2022 extension type discriminators (SPL Token-2022 §extension types).
// We only list the ones we want to surface in reports — anything else
// shows up as `unknown_<num>` so reviewers can investigate.
const TOKEN_2022_EXTENSION_NAMES: Record<number, string> = {
  1: 'TransferFeeConfig',
  2: 'TransferFeeAmount',
  3: 'MintCloseAuthority',
  4: 'ConfidentialTransferMint',
  5: 'ConfidentialTransferAccount',
  6: 'DefaultAccountState',
  7: 'ImmutableOwner',
  8: 'MemoTransfer',
  9: 'NonTransferable',
  10: 'InterestBearingConfig',
  11: 'CpiGuard',
  12: 'PermanentDelegate',
  13: 'NonTransferableAccount',
  14: 'TransferHook',
  15: 'TransferHookAccount',
  16: 'ConfidentialTransferFeeConfig',
  17: 'ConfidentialTransferFeeAmount',
  18: 'MetadataPointer',
  19: 'TokenMetadata',
  20: 'GroupPointer',
  21: 'TokenGroup',
  22: 'GroupMemberPointer',
  23: 'TokenGroupMember',
};

export function looksLikeSolanaAddress(value: string): boolean {
  return BASE58_RE.test(value.trim());
}

async function defaultFetchAccountInfo(
  programId: string,
  rpcUrl: string,
): Promise<RpcAccountInfo | null> {
  // Lazy import so unit tests that inject fetchAccountInfo don't pay the cost.
  const { Connection, PublicKey } = await import('@solana/web3.js');
  const conn = new Connection(rpcUrl, 'confirmed');
  const pk = new PublicKey(programId);
  const info = await conn.getAccountInfo(pk, 'confirmed');
  if (!info) return null;
  return {
    data: info.data,
    owner: info.owner.toBase58(),
    executable: info.executable,
  };
}

// =============================================================================
// On-chain authority parsers — pure byte-level, no @solana/web3.js needed
// =============================================================================

/**
 * Decode a 32-byte slice as a base58 string.
 *
 * Lazy-imports `@solana/web3.js`'s PublicKey because it already ships a
 * battle-tested base58 encoder; bringing in `bs58` separately would mean
 * one more dep in `package.json` for ~50 lines of code.
 */
async function pubkeyFromBytes(slice: Uint8Array): Promise<string> {
  const { PublicKey } = await import('@solana/web3.js');
  return new PublicKey(slice).toBase58();
}

/**
 * Parse an SPL Token (legacy or Token-2022) Mint account. Layout:
 *
 *   offset 0..3   — mint_authority COption tag (LE u32, 0=None / 1=Some)
 *   offset 4..35  — mint_authority pubkey (zeroed if None)
 *   offset 36..43 — supply (u64 LE)
 *   offset 44     — decimals (u8)
 *   offset 45     — is_initialized (bool)
 *   offset 46..49 — freeze_authority COption tag
 *   offset 50..81 — freeze_authority pubkey
 *
 * Total 82 bytes. Token-2022 mints are padded to 165 bytes and may have
 * TLV-encoded extensions starting at offset 165.
 */
async function parseMint(
  data: Uint8Array,
): Promise<{ mintAuthority: string | null; freezeAuthority: string | null }> {
  if (data.length < 82) {
    throw new Error(`mint account too short (${data.length} bytes, expected ≥82)`);
  }
  const view = Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  const mintAuthOption = view.readUInt32LE(0);
  const mintAuthority =
    mintAuthOption === 1 ? await pubkeyFromBytes(data.slice(4, 36)) : null;
  const freezeAuthOption = view.readUInt32LE(46);
  const freezeAuthority =
    freezeAuthOption === 1 ? await pubkeyFromBytes(data.slice(50, 82)) : null;
  return { mintAuthority, freezeAuthority };
}

/**
 * Walk the TLV extension table after the 165-byte Token-2022 mint base.
 * Each TLV: 2-byte type (u16 LE) + 2-byte length (u16 LE) + length bytes.
 * Stops on type=0 (Uninitialized sentinel) or end of buffer.
 */
function parseToken2022Extensions(data: Uint8Array): string[] {
  const EXT_BASE_OFFSET = 165;
  if (data.length <= EXT_BASE_OFFSET) return [];
  const view = Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  const extensions: string[] = [];
  let offset = EXT_BASE_OFFSET;
  // Token-2022 reserves byte 165 for the AccountType discriminator
  // (1 = Mint). Skip it before we start reading TLVs.
  if (view.readUInt8(EXT_BASE_OFFSET) === 1) offset = EXT_BASE_OFFSET + 1;
  while (offset + 4 <= view.length) {
    const type = view.readUInt16LE(offset);
    const len = view.readUInt16LE(offset + 2);
    if (type === 0 && len === 0) break;
    const name = TOKEN_2022_EXTENSION_NAMES[type] ?? `unknown_${type}`;
    extensions.push(name);
    offset += 4 + len;
    if (extensions.length > 32) break; // sanity cap
  }
  return extensions;
}

/**
 * Decode an UpgradeableLoaderState::Program account.
 *
 *   offset 0..3   — enum tag (LE u32, 2 = Program)
 *   offset 4..35  — programdata_address pubkey
 */
async function parseUpgradeableProgramAccount(
  data: Uint8Array,
): Promise<{ programDataAddress: string } | null> {
  if (data.length < 36) return null;
  const view = Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  const tag = view.readUInt32LE(0);
  if (tag !== 2) return null;
  return {
    programDataAddress: await pubkeyFromBytes(data.slice(4, 36)),
  };
}

/**
 * Decode an UpgradeableLoaderState::ProgramData header.
 *
 *   offset 0..3   — enum tag (LE u32, 3 = ProgramData)
 *   offset 4..11  — slot (u64 LE)
 *   offset 12     — upgrade_authority Option tag (1 byte, 0=None / 1=Some)
 *   offset 13..44 — upgrade_authority pubkey
 *
 * Bytecode follows. We only need the header.
 */
async function parseProgramDataHeader(
  data: Uint8Array,
): Promise<{ upgradeAuthority: string | null } | null> {
  if (data.length < 13) return null;
  const view = Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  const tag = view.readUInt32LE(0);
  if (tag !== 3) return null;
  const optionTag = view.readUInt8(12);
  if (optionTag === 0) return { upgradeAuthority: null };
  if (data.length < 45) return null;
  return {
    upgradeAuthority: await pubkeyFromBytes(data.slice(13, 45)),
  };
}

/**
 * Top-level dispatcher: classify by owner, parse appropriately, and
 * return a structured snapshot. Always succeeds with at least
 * `{ owner, executable, kind: 'unknown' }` so callers don't have to
 * handle null vs partial.
 */
async function fetchOnchainAuthority(
  primary: RpcAccountInfo,
  programId: string,
  fetchFn: (id: string) => Promise<RpcAccountInfo | null>,
): Promise<OnchainAuthority> {
  const base: OnchainAuthority = {
    owner: primary.owner,
    executable: primary.executable,
    kind: 'unknown',
  };

  // ---- SPL Token (legacy) -------------------------------------------------
  if (primary.owner === TOKEN_PROGRAM_ID) {
    try {
      const { mintAuthority, freezeAuthority } = await parseMint(primary.data);
      return { ...base, kind: 'mint', mintAuthority, freezeAuthority };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ...base, kind: 'unknown', parseNote: `mint parse failed: ${msg}` };
    }
  }

  // ---- SPL Token-2022 -----------------------------------------------------
  if (primary.owner === TOKEN_2022_PROGRAM_ID) {
    try {
      const { mintAuthority, freezeAuthority } = await parseMint(primary.data);
      const extensions = parseToken2022Extensions(primary.data);
      return {
        ...base,
        kind: 'mint-2022',
        mintAuthority,
        freezeAuthority,
        token2022Extensions: extensions,
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ...base, kind: 'unknown', parseNote: `mint-2022 parse failed: ${msg}` };
    }
  }

  // ---- BPFLoaderUpgradeable program ---------------------------------------
  if (primary.owner === BPF_LOADER_UPGRADEABLE) {
    try {
      const programInfo = await parseUpgradeableProgramAccount(primary.data);
      if (!programInfo) {
        return {
          ...base,
          kind: 'unknown',
          parseNote: 'expected Program enum tag (2), got something else',
        };
      }
      const programDataAccount = await fetchFn(programInfo.programDataAddress);
      if (!programDataAccount) {
        return {
          ...base,
          kind: 'program-upgradeable',
          parseNote: `programdata account ${programInfo.programDataAddress} not found`,
        };
      }
      const header = await parseProgramDataHeader(programDataAccount.data);
      if (!header) {
        return {
          ...base,
          kind: 'program-upgradeable',
          parseNote: 'programdata header parse failed',
        };
      }
      return {
        ...base,
        kind: 'program-upgradeable',
        upgradeAuthority: header.upgradeAuthority,
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        ...base,
        kind: 'program-upgradeable',
        parseNote: `programdata fetch failed: ${msg}`,
      };
    }
  }

  // ---- Finalised program (legacy BPFLoader / BPFLoader2) ------------------
  if (primary.owner === BPF_LOADER_2 || primary.owner === BPF_LOADER_LEGACY) {
    return { ...base, kind: 'program-finalised', upgradeAuthority: null };
  }

  // ---- Unknown owner ------------------------------------------------------
  return base;
}

export async function normalizeContractAddress(
  input: AuditInput,
  workdir: string,
  deps: AddressNormalizerDeps = {},
): Promise<NormalizedInput> {
  const programId = input.value.trim();
  if (!looksLikeSolanaAddress(programId)) {
    throw new Error(`not a valid base58 Solana address: ${programId}`);
  }

  const rpcUrl = deps.rpcUrl ?? config.solanaRpcUrl;
  const fetchFn = deps.fetchAccountInfo ?? ((pid) => defaultFetchAccountInfo(pid, rpcUrl));

  logger.debug({ programId, rpcUrl }, 'address: fetching account info');
  const info = await fetchFn(programId);
  if (!info) {
    throw new Error(`account not found on RPC (${rpcUrl}): ${programId}`);
  }
  if (!info.executable && info.owner !== TOKEN_PROGRAM_ID && info.owner !== TOKEN_2022_PROGRAM_ID) {
    logger.warn(
      { programId, owner: info.owner },
      'address: target is not an executable program and not a token mint (unknown account class)',
    );
  }

  // Pull the on-chain authority snapshot. This may issue a second RPC
  // call (for upgradeable programs we need to fetch ProgramData), but
  // failures degrade gracefully — we never abort the whole normalize on
  // an authority-parse failure since users can still get a code-only
  // audit on the bytecode itself.
  let onchain: OnchainAuthority | undefined;
  try {
    onchain = await fetchOnchainAuthority(info, programId, fetchFn);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    logger.warn({ err: msg, programId }, 'address: onchain authority parse failed');
  }

  const outDir = path.resolve(workdir, 'bytecode');
  mkdirSync(outDir, { recursive: true });
  const bytecodePath = path.join(outDir, `${programId}.so`);
  writeFileSync(bytecodePath, Buffer.from(info.data));

  return {
    kind: 'bytecode_only',
    programId,
    bytecodePath,
    onchain,
    origin: { type: 'contract_address', value: input.value },
  };
}
