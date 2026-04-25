// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// Client-side Solana Pay transaction builder. Mirrors the backend's
// `createPaymentRequest` / `verifyPayment` contract (see solguard-server/src/payment.ts):
//
//   - System transfer from user → recipient, exact `lamports = amountSol * 1e9`
//   - Extra readonly key on that transfer instruction carrying the payment
//     `reference` PublicKey so the backend poller can later locate the tx
//     via `findReference(connection, reference)` and validate it with
//     `validateTransfer`.
//
// We request the connected wallet to sign & send via `signAndSendTransaction`,
// which covers all wallet-standard-compatible providers (Phantom / Backpack /
// Solflare). Returns the broadcast signature; callers then POST it to
// `/api/audit/:id/payment` for on-chain verification.

const DEVNET_RPC = 'https://api.devnet.solana.com';

/** Build a memo-free transfer tx with `reference` attached as a readonly key. */
export async function buildPaymentTx({
  userPubkey,
  recipient,
  amountSol,
  reference,
  rpcUrl = DEVNET_RPC,
}) {
  const { Connection, PublicKey, Transaction, SystemProgram } =
    window.solanaWeb3;
  const conn = new Connection(rpcUrl, 'confirmed');
  const { blockhash, lastValidBlockHeight } =
    await conn.getLatestBlockhash('confirmed');

  const fromPubkey = new PublicKey(userPubkey);
  const toPubkey = new PublicKey(recipient);
  const referenceKey = new PublicKey(reference);

  const lamports = Math.round(amountSol * 1e9);
  if (!Number.isFinite(lamports) || lamports <= 0) {
    throw new Error(`Invalid amount: ${amountSol} SOL`);
  }

  const ix = SystemProgram.transfer({ fromPubkey, toPubkey, lamports });
  // Attach `reference` as a readonly, non-signer key so validateTransfer
  // on the backend can match this tx to the task.
  ix.keys.push({ pubkey: referenceKey, isSigner: false, isWritable: false });

  const tx = new Transaction({
    feePayer: fromPubkey,
    recentBlockhash: blockhash,
  }).add(ix);

  return { tx, conn, blockhash, lastValidBlockHeight };
}

/**
 * Ask the injected wallet to sign + send. Supports the modern
 * `signAndSendTransaction` wallet-standard API (Phantom, Backpack, Solflare).
 * Falls back to `signTransaction` + manual broadcast if needed.
 */
export async function signAndSend({ provider, tx, conn }) {
  // In demo mode with a real wallet, Phantom's signAndSendTransaction uses
  // whatever cluster the wallet UI is pointed at — if the user left it on
  // mainnet our devnet-blockhash tx would be rejected. Force the manual
  // sign + broadcast path so `conn` (always devnet) is the broadcast route.
  const forceManualBroadcast =
    typeof window !== 'undefined' &&
    window.__SOLGUARD_DEMO &&
    !window.__SOLGUARD_DEMO_MOCK_WALLET;

  if (
    !forceManualBroadcast &&
    typeof provider.signAndSendTransaction === 'function'
  ) {
    const { signature } = await provider.signAndSendTransaction(tx);
    return signature;
  }
  if (typeof provider.signTransaction === 'function') {
    const signed = await provider.signTransaction(tx);
    const sig = await conn.sendRawTransaction(signed.serialize(), {
      skipPreflight: false,
    });
    return sig;
  }
  throw new Error('Wallet does not support signing Solana transactions');
}

/**
 * Block until the given signature is confirmed (status >= confirmed).
 * Uses the new `confirmTransaction` shape to avoid deprecated-signature
 * warnings on recent @solana/web3.js.
 */
export async function waitForConfirmation({
  conn,
  signature,
  blockhash,
  lastValidBlockHeight,
  timeoutMs = 90_000,
}) {
  const start = Date.now();
  try {
    await conn.confirmTransaction(
      { signature, blockhash, lastValidBlockHeight },
      'confirmed',
    );
  } catch (e) {
    // fall through to polling below
  }

  while (Date.now() - start < timeoutMs) {
    const st = await conn.getSignatureStatus(signature, {
      searchTransactionHistory: true,
    });
    const val = st?.value;
    if (
      val?.confirmationStatus === 'confirmed' ||
      val?.confirmationStatus === 'finalized'
    ) {
      if (val?.err) {
        throw new Error('Transaction failed on-chain: ' + JSON.stringify(val.err));
      }
      return true;
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
  throw new Error('Timed out waiting for transaction confirmation');
}

/** Full one-shot flow: build → sign → send → confirm. Returns the signature. */
export async function payAudit({
  provider,
  userPubkey,
  recipient,
  amountSol,
  reference,
  rpcUrl,
  onSignatureBroadcast,
}) {
  // Demo mode short-circuit — only when we also installed the mock wallet.
  // If the visitor has a real Phantom we fall through to the live path and
  // actually transfer `amountSol` to `recipient` on devnet, because seeing
  // their balance drop is the point of the hybrid demo.
  if (typeof window !== 'undefined' && window.__SOLGUARD_DEMO_MOCK_WALLET) {
    const demoSig =
      'demoSigDemoSigDemoSigDemoSigDemoSigDemoSigDemoSigDemoSigDemoSig11';
    await new Promise((r) => setTimeout(r, 600));
    onSignatureBroadcast?.(demoSig);
    await new Promise((r) => setTimeout(r, 600));
    return demoSig;
  }

  const { tx, conn, blockhash, lastValidBlockHeight } =
    await buildPaymentTx({
      userPubkey,
      recipient,
      amountSol,
      reference,
      rpcUrl,
    });
  const signature = await signAndSend({ provider, tx, conn });
  onSignatureBroadcast?.(signature);
  await waitForConfirmation({
    conn,
    signature,
    blockhash,
    lastValidBlockHeight,
  });
  return signature;
}
