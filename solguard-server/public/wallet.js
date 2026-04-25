// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// Phantom wallet connector. Uses the injected window.solana provider
// (Phantom / Backpack / Solflare all implement a compatible API).

const DEVNET_RPC = 'https://api.devnet.solana.com';

export function hasPhantom() {
  return Boolean(window.solana?.isPhantom);
}

export function hasInjectedWallet() {
  return Boolean(window.solana);
}

/** Opens the wallet download page in a new tab. */
export function openPhantomInstall() {
  window.open('https://phantom.app/download', '_blank', 'noopener');
}

/**
 * Connect to the user's wallet, returning { publicKey: string, provider }.
 * Throws if no provider is present or the user rejects.
 */
export async function connect() {
  if (!hasInjectedWallet()) {
    const err = new Error(
      'No Solana wallet detected. Install Phantom to continue.',
    );
    err.code = 'NO_WALLET';
    throw err;
  }
  const provider = window.solana;
  try {
    const resp = await provider.connect();
    const pk = resp.publicKey ?? provider.publicKey;
    if (!pk) throw new Error('Wallet returned no public key');
    return { publicKey: pk.toString(), provider };
  } catch (e) {
    if (e?.code === 4001 || /reject/i.test(e?.message ?? '')) {
      const err = new Error('Connection cancelled');
      err.code = 'USER_REJECTED';
      throw err;
    }
    throw e;
  }
}

export async function disconnect() {
  try {
    await window.solana?.disconnect?.();
  } catch {
    /* ignore */
  }
}

export function onAccountChange(cb) {
  window.solana?.on?.('accountChanged', (pub) => {
    cb(pub ? pub.toString() : null);
  });
}

export function onDisconnect(cb) {
  window.solana?.on?.('disconnect', cb);
}

/** Devnet SOL balance (in SOL) of the given public key. */
export async function getBalanceSol(publicKeyStr, rpcUrl = DEVNET_RPC) {
  // Demo mode short-circuit — only when we also installed the mock wallet.
  // If the visitor has a real Phantom (__SOLGUARD_DEMO_MOCK_WALLET === false)
  // we still hit devnet RPC so they see their actual balance.
  if (typeof window !== 'undefined' && window.__SOLGUARD_DEMO_MOCK_WALLET) {
    return 2.5;
  }
  const { Connection, PublicKey } = window.solanaWeb3;
  const conn = new Connection(rpcUrl, 'confirmed');
  const lamports = await conn.getBalance(new PublicKey(publicKeyStr));
  return lamports / 1e9;
}

/** Short address like "Abcd…wxyz" for display. */
export function shortAddr(addr) {
  if (!addr) return '—';
  const s = String(addr);
  if (s.length <= 10) return s;
  return s.slice(0, 4) + '…' + s.slice(-4);
}
