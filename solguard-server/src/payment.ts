// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { encodeURL, findReference, validateTransfer } from '@solana/pay';
import {
  Connection,
  Keypair,
  PublicKey,
  type ConfirmedSignatureInfo,
} from '@solana/web3.js';
import BigNumber from 'bignumber.js';
import { config } from './config';
import { logger } from './logger';

const SOL_LABEL = 'SolGuard Security Audit';
const SOL_MEMO = 'SolGuard audit payment';

let connectionSingleton: Connection | null = null;

export function getConnection(): Connection {
  if (!connectionSingleton) {
    connectionSingleton = new Connection(config.solanaRpcUrl, 'confirmed');
  }
  return connectionSingleton;
}

export interface PaymentRequest {
  url: string;
  reference: string;
  recipient: string;
  amountSol: number;
  memo: string;
  expiresAt: string;
}

export function createPaymentRequest(params: {
  /** Task or batch identifier; used only for the on-chain message. */
  taskId: string;
  recipient?: string;
  amountSol?: number;
  label?: string;
  message?: string;
}): PaymentRequest {
  const recipientStr = params.recipient ?? config.solanaServiceWallet;
  if (!recipientStr) {
    throw new Error('SOLANA_SERVICE_WALLET is not configured');
  }

  const recipient = new PublicKey(recipientStr);
  const amount = new BigNumber(params.amountSol ?? config.auditPriceSol);
  const reference = Keypair.generate().publicKey;
  const label = params.label ?? SOL_LABEL;
  const message = params.message ?? `Audit task ${params.taskId}`;
  const memo = SOL_MEMO;

  const url = encodeURL({
    recipient,
    amount,
    reference,
    label,
    message,
    memo,
  });

  const expiresAt = new Date(Date.now() + config.paymentTimeoutMs).toISOString();

  return {
    url: url.toString(),
    reference: reference.toBase58(),
    recipient: recipient.toBase58(),
    amountSol: amount.toNumber(),
    memo,
    expiresAt,
  };
}

export interface VerifyResult {
  ok: boolean;
  signature?: string;
  error?: string;
}

export async function findPaymentSignature(
  connection: Connection,
  reference: PublicKey,
): Promise<ConfirmedSignatureInfo | null> {
  try {
    return await findReference(connection, reference, { finality: 'confirmed' });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes('not found')) return null;
    throw err;
  }
}

export async function verifyPayment(params: {
  connection?: Connection;
  signature: string;
  reference: string;
  recipient: string;
  amountSol: number;
}): Promise<VerifyResult> {
  const connection = params.connection ?? getConnection();
  try {
    await validateTransfer(
      connection,
      params.signature,
      {
        recipient: new PublicKey(params.recipient),
        amount: new BigNumber(params.amountSol),
        reference: new PublicKey(params.reference),
      },
      { commitment: 'confirmed' },
    );
    return { ok: true, signature: params.signature };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    logger.warn({ err: msg, signature: params.signature }, 'validateTransfer rejected');
    return { ok: false, error: msg };
  }
}
