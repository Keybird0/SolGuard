// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// Solana Pay QR support for the browser-only payment page. The real backend
// still owns final verification; this module only renders a Solana Pay URL
// and watches Devnet so the UI can auto-submit a discovered signature.

const QRCODE_SRC =
  'https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js';
const DEFAULT_RPC = 'https://api.devnet.solana.com';
const LAMPORTS_PER_SOL = 1_000_000_000;

let qrPromise = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('Failed to load ' + src));
    document.head.appendChild(s);
  });
}

async function ensureQrLib() {
  if (window.qrcode) return window.qrcode;
  if (!qrPromise) qrPromise = loadScript(QRCODE_SRC);
  await qrPromise;
  if (!window.qrcode) throw new Error('QR library did not initialize');
  return window.qrcode;
}

export function buildSolanaPayURL({
  recipient,
  amountSol,
  reference,
  batchId,
  label = 'SolGuard Security Audit',
}) {
  if (!recipient || !reference || !amountSol) {
    throw new Error('Missing Solana Pay parameters');
  }
  const url = new URL('solana:' + recipient);
  url.searchParams.set('amount', String(amountSol));
  url.searchParams.set('reference', reference);
  url.searchParams.set('label', label);
  url.searchParams.set(
    'message',
    batchId ? `Audit batch ${batchId}` : 'SolGuard audit payment',
  );
  url.searchParams.set('memo', 'SolGuard audit payment');
  return url.toString();
}

export async function renderQR(canvas, uri) {
  const qrcode = await ensureQrLib();
  const qr = qrcode(0, 'M');
  qr.addData(uri);
  qr.make();

  const ctx = canvas.getContext('2d');
  const modules = qr.getModuleCount();
  const size = Math.min(canvas.width, canvas.height);
  const quiet = 4;
  const cell = Math.floor(size / (modules + quiet * 2));
  const qrSize = cell * modules;
  const offset = Math.floor((size - qrSize) / 2);

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#111827';

  for (let row = 0; row < modules; row += 1) {
    for (let col = 0; col < modules; col += 1) {
      if (qr.isDark(row, col)) {
        ctx.fillRect(offset + col * cell, offset + row * cell, cell, cell);
      }
    }
  }
}

function lamportsFromSol(amountSol) {
  const n = Number(amountSol);
  if (!Number.isFinite(n) || n <= 0) {
    throw new Error('Invalid amount: ' + amountSol);
  }
  return Math.round(n * LAMPORTS_PER_SOL);
}

function keyToBase58(key) {
  if (!key) return '';
  if (typeof key === 'string') return key;
  if (typeof key.toBase58 === 'function') return key.toBase58();
  if (key.pubkey) return keyToBase58(key.pubkey);
  return String(key);
}

function accountKeysFromMessage(message) {
  if (!message) return [];
  if (Array.isArray(message.accountKeys)) return message.accountKeys.map(keyToBase58);
  if (Array.isArray(message.staticAccountKeys)) {
    return message.staticAccountKeys.map(keyToBase58);
  }
  return [];
}

function validateTransferTx(tx, { recipient, reference, amountSol }) {
  if (!tx || tx.meta?.err) return false;

  const keys = accountKeysFromMessage(tx.transaction?.message);
  if (!keys.includes(reference)) return false;

  const recipientIdx = keys.indexOf(recipient);
  if (recipientIdx < 0) return false;

  const pre = tx.meta?.preBalances?.[recipientIdx];
  const post = tx.meta?.postBalances?.[recipientIdx];
  if (!Number.isFinite(pre) || !Number.isFinite(post)) return false;

  return post - pre === lamportsFromSol(amountSol);
}

export function watchDevnetPayment({
  reference,
  recipient,
  amountSol,
  rpcUrl = DEFAULT_RPC,
  intervalMs = 3000,
  expiresAt,
  onFound,
  onValidated,
  onError,
}) {
  if (!window.solanaWeb3) {
    throw new Error('Solana web3 library is not loaded');
  }
  const { Connection, PublicKey } = window.solanaWeb3;
  const conn = new Connection(rpcUrl, 'confirmed');
  const referenceKey = new PublicKey(reference);
  let stopped = false;
  let timer = null;
  let running = false;
  const seen = new Set();

  async function tick() {
    if (stopped || running) return;
    if (expiresAt && Date.parse(expiresAt) < Date.now()) {
      stopped = true;
      onError?.(new Error('Payment request expired'));
      return;
    }
    running = true;
    try {
      const sigInfos = await conn.getSignaturesForAddress(
        referenceKey,
        { limit: 5 },
        'confirmed',
      );
      for (const sigInfo of sigInfos) {
        const signature = sigInfo.signature;
        if (!signature || seen.has(signature)) continue;
        seen.add(signature);
        onFound?.(signature);
        const tx = await conn.getTransaction(signature, {
          commitment: 'confirmed',
          maxSupportedTransactionVersion: 0,
        });
        if (validateTransferTx(tx, { recipient, reference, amountSol })) {
          stopped = true;
          if (timer) clearInterval(timer);
          onValidated?.(signature);
          return;
        }
      }
    } catch (err) {
      onError?.(err);
    } finally {
      running = false;
    }
  }

  timer = setInterval(tick, intervalMs);
  void tick();

  return {
    stop() {
      stopped = true;
      if (timer) clearInterval(timer);
      timer = null;
    },
  };
}
