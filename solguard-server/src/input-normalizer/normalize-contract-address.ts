// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { config } from '../config';
import { logger } from '../logger';
import type { AuditInput, NormalizedInput } from '../types';

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
  if (!info.executable) {
    logger.warn(
      { programId, owner: info.owner },
      'address: target is not an executable program (might be a mint/token account)',
    );
  }

  const outDir = path.resolve(workdir, 'bytecode');
  mkdirSync(outDir, { recursive: true });
  const bytecodePath = path.join(outDir, `${programId}.so`);
  writeFileSync(bytecodePath, Buffer.from(info.data));

  return {
    kind: 'bytecode_only',
    programId,
    bytecodePath,
    origin: { type: 'contract_address', value: input.value },
  };
}
