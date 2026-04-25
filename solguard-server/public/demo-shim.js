// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// SolGuard Demo Mode shim — installed by index.html BEFORE app.js runs.
//
// Activates automatically when:
//   - hostname ends with ".vercel.app" / ".vercel.sh", or
//   - URL has ?demo=1, or
//   - window.__SOLGUARD_DEMO was set by a previous script.
//
// When active, it intercepts `window.fetch` so all /api/* and /healthz calls
// return pre-canned responses driven by 3 case studies in /demo-data/.
//
// Hybrid wallet strategy
// ----------------------
// If the visitor has a real Phantom (or compatible) wallet injected at shim
// load time (window.solana?.isPhantom), we KEEP the real provider — the
// balance widget hits devnet RPC for real, and "Pay 0.003 SOL" broadcasts a
// real transfer to DEMO_RECIPIENT on devnet. The mock /api/* endpoints still
// serve the pre-canned reports, but the wallet half is live. This gives
// wallet-equipped visitors a tangible "I actually paid and saw my balance
// drop" experience.
//
// If no real wallet is present, we fall back to a mock window.solana and
// wallet.js / payment.js short-circuit to fake balance / fake signature.
//
// Two globals tell the rest of the page which mode we're in:
//   window.__SOLGUARD_DEMO            = true whenever the shim is active
//   window.__SOLGUARD_DEMO_MOCK_WALLET = true only when we installed the mock
// wallet.js + payment.js consult __SOLGUARD_DEMO_MOCK_WALLET (not the outer
// demo flag) to decide whether to skip real RPC / real signing.

(function initDemoShim() {
  'use strict';

  const host = (typeof location !== 'undefined' && location.hostname) || '';
  const queryHasDemo =
    typeof location !== 'undefined' &&
    /(^|[?&])demo=1(&|$)/.test(location.search || '');

  const autoDemo =
    host.endsWith('.vercel.app') ||
    host.endsWith('.vercel.sh') ||
    host === 'solguard-demo.local' ||
    queryHasDemo;

  if (!autoDemo && !window.__SOLGUARD_DEMO) {
    return;
  }

  window.__SOLGUARD_DEMO = true;
  // Tentative default: we'll refine after a short poll below, but set a safe
  // initial value so any ultra-early caller sees *some* answer. Start with
  // "mock" unless we already see a real wallet at this exact tick.
  const syncSaw = detectRealProviderSync();
  window.__SOLGUARD_DEMO_MOCK_WALLET = !syncSaw;

  /**
   * Synchronous probe for any wallet-standard provider that a browser
   * extension has injected. Phantom injects in two places:
   *   - window.phantom.solana  (modern, always available once injected)
   *   - window.solana          (legacy alias, set alongside the modern one)
   * Backpack / Solflare have their own namespaces. We mirror whichever we
   * find back onto window.solana so wallet.js (which only knows window.solana)
   * picks it up transparently.
   */
  function detectRealProviderSync() {
    const fromPhantomNs = window.phantom?.solana;
    if (fromPhantomNs?.isPhantom && !fromPhantomNs.isDemo) {
      if (!window.solana || window.solana.isDemo) window.solana = fromPhantomNs;
      return fromPhantomNs;
    }
    if (window.solana?.isPhantom && !window.solana.isDemo) return window.solana;
    if (window.backpack?.isBackpack) return window.backpack;
    if (window.solflare?.isSolflare) return window.solflare;
    return null;
  }

  // ============================================================
  // Demo banner — rendered once DOM is ready. Text flips between
  // "live wallet" / "mock wallet" after the async probe decides.
  // ============================================================
  function bannerText() {
    return window.__SOLGUARD_DEMO_MOCK_WALLET
      ? 'DEMO MODE — reports are pre-generated; no real scanning, no real Solana transactions happen here.'
      : 'DEMO MODE · audit reports are pre-generated — but your real Phantom will pay 0.003 SOL on Devnet for the demo.';
  }
  function renderBanner() {
    if (document.getElementById('demo-banner')) return;
    const bar = document.createElement('div');
    bar.id = 'demo-banner';
    bar.textContent = bannerText();
    bar.style.cssText = [
      'position:fixed',
      'top:0',
      'left:0',
      'right:0',
      'z-index:9999',
      'padding:8px 16px',
      'background:linear-gradient(90deg,#ffcf44,#ff8a3c)',
      'color:#141414',
      'font-family:Inter,system-ui,sans-serif',
      'font-size:13px',
      'font-weight:600',
      'text-align:center',
      'letter-spacing:0.01em',
      'box-shadow:0 2px 6px rgba(0,0,0,0.15)',
    ].join(';');
    document.body.appendChild(bar);
    document.body.style.paddingTop = '34px';
  }
  function updateBannerText() {
    const el = document.getElementById('demo-banner');
    if (el) el.textContent = bannerText();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderBanner, { once: true });
  } else {
    renderBanner();
  }

  // ============================================================
  // Mock Phantom provider. wallet.js calls provider.connect() and
  // provider.signAndSendTransaction(tx); payment.js short-circuits
  // this when __SOLGUARD_DEMO_MOCK_WALLET is true so the tx is never built.
  // ============================================================
  const DEMO_PUBKEY = 'Fi1ocNuvGaGP8dVSSCuhCkxzBe4Rt2jB89fBL8FnUBWD';
  const DEMO_SIGNATURE =
    'demoSigDemoSigDemoSigDemoSigDemoSigDemoSigDemoSigDemoSigDemoSig11';

  function installMockWallet() {
    // Guard: if a real wallet is injected (or our mock is already here), bail.
    if (window.solana && window.solana.isPhantom) return;
    if (!window.__SOLGUARD_DEMO_MOCK_WALLET) return;
    const listeners = { accountChanged: [], disconnect: [] };
    // Minimal PublicKey shim (wallet.js expects .toString()).
    const pk = { toString: () => DEMO_PUBKEY };
    window.solana = {
      isPhantom: true,
      isDemo: true,
      publicKey: pk,
      async connect() {
        return { publicKey: pk };
      },
      async disconnect() {
        listeners.disconnect.forEach((f) => f());
      },
      async signAndSendTransaction() {
        // payment.js short-circuits before this; kept for completeness.
        return { signature: DEMO_SIGNATURE };
      },
      on(event, cb) {
        if (listeners[event]) listeners[event].push(cb);
      },
      off(event, cb) {
        if (listeners[event]) {
          listeners[event] = listeners[event].filter((f) => f !== cb);
        }
      },
    };
  }

  // Async wallet probe — give Phantom / Backpack / Solflare up to ~900ms to
  // inject (some extensions are slow on cold starts / content-script restarts)
  // before committing to the mock. app.js only reads window.solana after the
  // user clicks "Connect Wallet", which is far later than this budget, so we
  // don't race against it.
  (async function finalizeWalletDecision() {
    const deadline = Date.now() + 900;
    let provider = detectRealProviderSync();
    while (!provider && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 60));
      provider = detectRealProviderSync();
    }
    if (provider) {
      window.__SOLGUARD_DEMO_MOCK_WALLET = false;
      console.info(
        '[SolGuard] Demo Mode — real wallet detected, balance + payment will hit Devnet RPC',
      );
    } else {
      window.__SOLGUARD_DEMO_MOCK_WALLET = true;
      console.info(
        '[SolGuard] Demo Mode — no wallet detected, installing mock Phantom',
      );
      installMockWallet();
    }
    updateBannerText();
  })();

  // ============================================================
  // In-memory batch state.
  //   batches: Map<batchId, { createdAt, paidAt?, taskIds[], email, cluster }>
  // Progress timeline (from paidAt):
  //   0s   scanning  (5%)
  //   3s   scanning  (40%)
  //   7s   analyzing (70%)
  //   11s  reporting (92%)
  //   15s  completed (100%)
  // ============================================================
  const SEEDED_REPORT_BATCH_ID = 'demo-sealevel-ai-first';
  const DEMO_CASES = ['case-sealevel', 'case-01', 'case-02', 'case-03'];
  const DEFAULT_CASES = ['case-sealevel'];
  const DEMO_AMOUNT = 0.001;
  const DEMO_RECIPIENT = 'DYmzG1oSfzJoVTSXedpn1mz3MqeH7H6ykV5RBsZJuD8i';

  /** @type {Map<string, any>} */
  const batches = new Map();

  function caseIdsForBatch(batch) {
    return Array.isArray(batch?.taskIds) && batch.taskIds.length
      ? batch.taskIds
      : DEFAULT_CASES;
  }

  function nowIso() {
    return new Date().toISOString();
  }
  function makeReference() {
    // Must be a real Solana public key: the live wallet path passes this to
    // new PublicKey(reference) and appends it as the Solana Pay reference key.
    try {
      return window.solanaWeb3.Keypair.generate().publicKey.toBase58();
    } catch {
      // Valid fallback public key; uniqueness is only needed for backend
      // polling, which the static Vercel demo intentionally mocks.
      return '11111111111111111111111111111112';
    }
  }

  function buildDemoSolanaPayUrl({ reference, amountSol, batchId }) {
    const url = new URL('solana:' + DEMO_RECIPIENT);
    url.searchParams.set('amount', String(amountSol));
    url.searchParams.set('reference', reference);
    url.searchParams.set('label', 'SolGuard Security Audit');
    url.searchParams.set('message', `Audit batch ${batchId}`);
    url.searchParams.set('memo', 'SolGuard audit payment');
    return url.toString();
  }

  function computeTaskState(batch, caseId, idx) {
    const createdAt = batch.createdAt;
    const updatedAt = nowIso();
    const base = {
      taskId: caseId,
      batchId: batch.batchId,
      email: batch.email,
      inputs: batch.inputsByCase[caseId] || [],
      paymentAmountSol: DEMO_AMOUNT,
      paymentRecipient: DEMO_RECIPIENT,
      paymentReference: batch.paymentReference,
      createdAt,
      updatedAt,
    };
    if (!batch.paidAt) {
      return { ...base, status: 'paying', progress: 'Awaiting payment', progressPercent: 3 };
    }
    const elapsed = (Date.now() - new Date(batch.paidAt).getTime()) / 1000;
    // Stagger each task by idx * 0.8s so they don't all complete at the
    // exact same frame; keeps the UI livelier.
    const t = elapsed - idx * 0.8;
    let status = 'paid';
    let progress = 'Paid — queued';
    let percent = 10;
    if (t >= 15) {
      status = 'completed';
      progress = 'Completed';
      percent = 100;
    } else if (t >= 11) {
      status = 'reporting';
      progress = 'Composing report…';
      percent = 92;
    } else if (t >= 7) {
      status = 'analyzing';
      progress = 'AI cross-validation + exploration…';
      percent = 70;
    } else if (t >= 3) {
      status = 'scanning';
      progress = 'Running rule scanner…';
      percent = 40;
    } else if (t >= 0) {
      status = 'scanning';
      progress = 'Parsing Rust / Anchor AST…';
      percent = 15;
    }

    const task = {
      ...base,
      status,
      progress,
      progressPercent: percent,
    };
    if (status === 'completed') {
      task.completedAt = new Date(
        new Date(batch.paidAt).getTime() + (15 + idx * 0.8) * 1000,
      ).toISOString();
      const rep = demoReports[caseId];
      task.statistics = rep?.statistics;
      task.findings = rep?.findings;
    }
    return task;
  }

  function computeBatch(batch) {
    const caseIds = caseIdsForBatch(batch);
    const tasks = caseIds.map((c, i) => computeTaskState(batch, c, i));
    const allCompleted = tasks.every((t) => t.status === 'completed');
    const allFailed = tasks.every((t) => t.status === 'failed');
    const status = batch.paidAt
      ? (allFailed ? 'failed' : 'paid')
      : 'paying';
    return {
      batch: {
        batchId: batch.batchId,
        taskIds: caseIds.slice(),
        email: batch.email,
        status,
        totalAmountSol: caseIds.length * DEMO_AMOUNT,
        paymentReference: batch.paymentReference,
        paymentRecipient: DEMO_RECIPIENT,
        paymentUrl: buildDemoSolanaPayUrl({
          reference: batch.paymentReference,
          amountSol: caseIds.length * DEMO_AMOUNT,
          batchId: batch.batchId,
        }),
        paymentSignature: batch.paymentSignature,
        paymentExpiresAt: batch.paymentExpiresAt,
        paymentConfirmedAt: batch.paidAt,
        cluster: 'devnet',
        freeAudit: false,
        createdAt: batch.createdAt,
        updatedAt: nowIso(),
      },
      tasks,
      allCompleted,
    };
  }

  batches.set(SEEDED_REPORT_BATCH_ID, {
    batchId: SEEDED_REPORT_BATCH_ID,
    taskIds: DEFAULT_CASES.slice(),
    email: 'demo@solguard.xyz',
    inputsByCase: {
      'case-sealevel': [
        { type: 'github', value: 'https://github.com/coral-xyz/sealevel-attacks' },
      ],
    },
    paymentReference: makeReference(),
    paymentExpiresAt: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
    paymentSignature: DEMO_SIGNATURE,
    paidAt: new Date(Date.now() - 60 * 1000).toISOString(),
    createdAt: new Date(Date.now() - 90 * 1000).toISOString(),
  });

  function restoreCompletedDemoBatch(batchId) {
    if (batchId !== SEEDED_REPORT_BATCH_ID && !/^demo-[a-z0-9-]+$/i.test(batchId)) {
      return null;
    }
    const batch = {
      batchId,
      taskIds: DEFAULT_CASES.slice(),
      email: 'demo@solguard.xyz',
      inputsByCase: {
        'case-sealevel': [
          { type: 'github', value: 'https://github.com/coral-xyz/sealevel-attacks' },
        ],
      },
      paymentReference: makeReference(),
      paymentExpiresAt: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
      paymentSignature: DEMO_SIGNATURE,
      paidAt: new Date(Date.now() - 60 * 1000).toISOString(),
      createdAt: new Date(Date.now() - 90 * 1000).toISOString(),
    };
    batches.set(batchId, batch);
    return batch;
  }

  const originalFetch = window.fetch.bind(window);

  // ============================================================
  // Demo report cache (loaded lazily from /demo-data/*/report.json).
  // Key: caseId → { findings[], statistics, reportMarkdown }
  // ============================================================
  const demoReports = {};
  const reportLoadPromises = {};

  async function loadCaseReport(caseId) {
    if (demoReports[caseId]) return demoReports[caseId];
    if (reportLoadPromises[caseId]) return reportLoadPromises[caseId];
    reportLoadPromises[caseId] = (async () => {
      const [json, rs, as_, cl] = await Promise.all([
        originalFetch(`/demo-data/${caseId}/report.json`).then((r) => r.json()),
        originalFetch(`/demo-data/${caseId}/risk_summary.md`).then((r) => r.text()),
        originalFetch(`/demo-data/${caseId}/assessment.md`).then((r) => r.text()),
        originalFetch(`/demo-data/${caseId}/checklist.md`).then((r) => r.text()),
      ]);
      const findings = (json.findings || []).map((f, i) => ({
        id: f.id || `F-${String(i + 1).padStart(3, '0')}`,
        ruleId: f.rule_id,
        severity: f.severity,
        title: f.title,
        location: f.location,
        description: f.description,
        impact: f.impact,
        recommendation: f.recommendation,
        codeSnippet: f.code_snippet,
        confidence: f.confidence,
      }));
      const reportMarkdown = [rs, as_, cl].join('\n\n');
      const cached = {
        statistics: json.statistics,
        findings,
        reportMarkdown,
        reportJson: json,
      };
      demoReports[caseId] = cached;
      return cached;
    })();
    return reportLoadPromises[caseId];
  }
  // Preload all 3 reports so the progress UI advances smoothly without
  // blocking on sequential text fetches.
  DEMO_CASES.forEach((c) => {
    loadCaseReport(c).catch((e) =>
      console.warn('[SolGuard demo] preload failed', c, e),
    );
  });

  // ============================================================
  // Fetch interceptor.
  // ============================================================
  function jsonResponse(body, status = 200) {
    return new Response(JSON.stringify(body), {
      status,
      headers: {
        'Content-Type': 'application/json',
        'X-Request-Id': 'demo-req-' + Math.random().toString(36).slice(2, 10),
      },
    });
  }
  function textResponse(body, contentType = 'text/markdown', status = 200) {
    return new Response(body, {
      status,
      headers: {
        'Content-Type': contentType,
        'X-Request-Id': 'demo-req-' + Math.random().toString(36).slice(2, 10),
      },
    });
  }

  function pathFromInput(input) {
    try {
      if (typeof input === 'string') {
        if (input.startsWith('/')) return input.split('?')[0];
        const u = new URL(input, location.origin);
        return u.origin === location.origin ? u.pathname : null;
      }
      if (input && typeof input === 'object' && typeof input.url === 'string') {
        const u = new URL(input.url, location.origin);
        return u.origin === location.origin ? u.pathname : null;
      }
    } catch {
      // fall through
    }
    return null;
  }

  function methodFromInit(input, init) {
    if (init && init.method) return String(init.method).toUpperCase();
    if (input && typeof input === 'object' && input.method)
      return String(input.method).toUpperCase();
    return 'GET';
  }

  async function handleRequest(path, method, body) {
    // ---- /healthz ---------------------------------------------------------
    if (path === '/healthz') {
      return jsonResponse({
        status: 'ok',
        version: '0.7.0-demo',
        environment: 'demo',
        checks: {
          ohCli: false,
          smtp: true,
          paymentPoller: false,
          auditPriceSol: DEMO_AMOUNT,
          freeAudit: false,
        },
        timestamp: nowIso(),
      });
    }

    // ---- POST /api/audit --------------------------------------------------
    if (path === '/api/audit' && method === 'POST') {
      const parsed = body ? JSON.parse(body) : {};
      const batchId = 'demo-' + Math.random().toString(36).slice(2, 10);
      const reference = makeReference();
      const email = parsed.email || 'demo@solguard.xyz';

      // Map the submitted targets (up to 3) onto our 3 case studies so the
      // progress + report UI echo back the exact fields the user submitted.
      // When the user submitted fewer / more than 3 we fall back to the
      // pre-canned demo labels to keep the batch visually complete.
      const demoInputsFallback = {
        'case-sealevel': [{ type: 'github', value: 'https://github.com/coral-xyz/sealevel-attacks' }],
        'case-01': [{ type: 'github', value: 'coral-xyz/sealevel-attacks (arbitrary-cpi)' }],
        'case-02': [{ type: 'github', value: 'SolGuard/fixtures/clean-escrow' }],
        'case-03': [{ type: 'github', value: 'SolGuard/fixtures/staking-slice' }],
      };
      function targetToInputs(t) {
        if (!t || typeof t !== 'object') return null;
        const list = [];
        if (t.github) list.push({ type: 'github', value: t.github });
        if (t.contractAddress)
          list.push({ type: 'contract_address', value: t.contractAddress });
        if (t.whitepaper) list.push({ type: 'whitepaper', value: t.whitepaper });
        if (t.website) list.push({ type: 'website', value: t.website });
        if (t.moreInfo) list.push({ type: 'more_info', value: t.moreInfo });
        return list.length ? list : null;
      }
      const submittedTargets = Array.isArray(parsed.targets) ? parsed.targets : [];
      const selectedCases = submittedTargets.length
        ? DEMO_CASES.slice(0, Math.min(submittedTargets.length, DEMO_CASES.length))
        : DEFAULT_CASES.slice();
      const demoInputs = {};
      selectedCases.forEach((caseId, i) => {
        const echoed = targetToInputs(submittedTargets[i]);
        demoInputs[caseId] = echoed || demoInputsFallback[caseId];
      });

      const batch = {
        batchId,
        taskIds: selectedCases.slice(),
        email,
        inputsByCase: demoInputs,
        paymentReference: reference,
        paymentExpiresAt: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
        paymentSignature: undefined,
        paidAt: null,
        createdAt: nowIso(),
      };
      batches.set(batchId, batch);

      return jsonResponse({
        batchId,
        taskIds: selectedCases.slice(),
        status: 'paying',
        paymentUrl: buildDemoSolanaPayUrl({
          reference,
          amountSol: selectedCases.length * DEMO_AMOUNT,
          batchId,
        }),
        paymentReference: reference,
        recipient: DEMO_RECIPIENT,
        amountSol: selectedCases.length * DEMO_AMOUNT,
        cluster: 'devnet',
        expiresAt: batch.paymentExpiresAt,
        freeAudit: false,
      });
    }

    // ---- POST /api/audit/batch/:id/payment -------------------------------
    // When a real wallet signed + broadcast the tx, the client POSTs the
    // real base58 signature in the body. We echo it back so the UI's "View
    // on Solscan" link opens the user's actual transaction on devnet.
    let m = path.match(/^\/api\/audit\/batch\/([^/]+)\/payment$/);
    if (m && method === 'POST') {
      const batch = batches.get(m[1]) || restoreCompletedDemoBatch(m[1]);
      if (!batch) return jsonResponse({ code: 'NOT_FOUND', message: 'Batch not found' }, 404);
      let providedSig;
      try { providedSig = body ? JSON.parse(body)?.signature : undefined; } catch { /* ignore */ }
      const isReal = typeof providedSig === 'string' && providedSig.length >= 40 && providedSig !== DEMO_SIGNATURE;
      // If the caller already waited for on-chain confirmation (real wallet
      // path), skip the cosmetic 1.5s delay. Otherwise keep it so the mock
      // path still shows the "Confirming…" state briefly.
      if (!isReal) {
        await new Promise((r) => setTimeout(r, 1500));
      }
      batch.paidAt = nowIso();
      batch.paymentSignature = providedSig || DEMO_SIGNATURE;
      return jsonResponse({ ok: true, status: 'paid', signature: batch.paymentSignature });
    }

    // ---- POST /api/audit/:id/payment (per-task; UI may still call this) --
    m = path.match(/^\/api\/audit\/([^/]+)\/payment$/);
    if (m && method === 'POST') {
      let providedSig;
      try { providedSig = body ? JSON.parse(body)?.signature : undefined; } catch { /* ignore */ }
      const isReal = typeof providedSig === 'string' && providedSig.length >= 40 && providedSig !== DEMO_SIGNATURE;
      // Find the batch whose taskIds include this taskId; if none match but
      // the caller passed a batchId-shaped value, accept it as a batch pay.
      let target = null;
      for (const batch of batches.values()) {
        if (batch.taskIds?.includes?.(m[1]) || batch.batchId === m[1]) {
          target = batch;
          break;
        }
      }
      if (!target) target = restoreCompletedDemoBatch(m[1]);
      if (!target && DEMO_CASES.includes(m[1])) {
        // Synthesize a single-task batch on the fly so UI can continue.
        target = restoreCompletedDemoBatch('demo-' + Math.random().toString(36).slice(2, 10));
      }
      if (!target) return jsonResponse({ code: 'NOT_FOUND', message: 'Task not found' }, 404);
      if (!isReal) await new Promise((r) => setTimeout(r, 1500));
      target.paidAt = target.paidAt || nowIso();
      target.paymentSignature = providedSig || DEMO_SIGNATURE;
      return jsonResponse({ ok: true, status: 'paid', signature: target.paymentSignature });
    }

    // ---- GET /api/audit/batch/:id ----------------------------------------
    m = path.match(/^\/api\/audit\/batch\/([^/]+)$/);
    if (m && method === 'GET') {
      const batch = batches.get(m[1]) || restoreCompletedDemoBatch(m[1]);
      if (!batch) return jsonResponse({ code: 'NOT_FOUND', message: 'Batch not found' }, 404);
      const computed = computeBatch(batch);
      // For every task that already reached "completed", block on its
      // demo report json/md. This closes a race where preloadCaseReport()
      // is still in-flight at the moment the report page mounts, and
      // hydrateReport() would otherwise land on tasks[0] with empty
      // statistics / findings and stay stuck on "Loading…".
      await Promise.all(
        computed.tasks.map(async (t) => {
          if (t.status !== 'completed' || !DEMO_CASES.includes(t.taskId)) return;
          try {
            const rep = await loadCaseReport(t.taskId);
            t.statistics = rep.statistics;
            t.findings = rep.findings;
            t.reportMarkdown = rep.reportMarkdown;
          } catch (err) {
            console.warn('[SolGuard demo] loadCaseReport failed for', t.taskId, err);
          }
        }),
      );
      return jsonResponse({ batch: computed.batch, tasks: computed.tasks });
    }

    // ---- GET /api/audit/:id/report.md ------------------------------------
    m = path.match(/^\/api\/audit\/([^/]+)\/report\.md$/);
    if (m && method === 'GET') {
      const caseId = DEMO_CASES.includes(m[1]) ? m[1] : null;
      if (!caseId) return textResponse('Not found', 'text/plain', 404);
      const rep = await loadCaseReport(caseId);
      return textResponse(rep.reportMarkdown);
    }

    // ---- GET /api/audit/:id/report.json ----------------------------------
    m = path.match(/^\/api\/audit\/([^/]+)\/report\.json$/);
    if (m && method === 'GET') {
      const caseId = DEMO_CASES.includes(m[1]) ? m[1] : null;
      if (!caseId) return jsonResponse({ code: 'NOT_FOUND', message: 'Not found' }, 404);
      const rep = await loadCaseReport(caseId);
      return jsonResponse(rep.reportJson);
    }

    // ---- GET /api/audit/:id ----------------------------------------------
    m = path.match(/^\/api\/audit\/([^/]+)$/);
    if (m && method === 'GET') {
      const caseId = m[1];
      // Find a batch that owns this taskId (handles in-memory flow), then
      // fall through to synthesize one from static data so page refresh /
      // deep links always render, even when batches Map was wiped.
      let batch = null;
      for (const candidate of batches.values()) {
        if (candidate.taskIds?.includes?.(caseId)) {
          batch = candidate;
          break;
        }
      }
      if (!batch && DEMO_CASES.includes(caseId)) {
        batch = restoreCompletedDemoBatch(SEEDED_REPORT_BATCH_ID);
      }
      if (!batch) return jsonResponse({ code: 'NOT_FOUND', message: 'Task not found' }, 404);
      const idx = (batch.taskIds || []).indexOf(caseId);
      const task = computeTaskState(batch, caseId, Math.max(idx, 0));
      if (task.status === 'completed' && DEMO_CASES.includes(caseId)) {
        const rep = await loadCaseReport(caseId);
        task.statistics = rep.statistics;
        task.findings = rep.findings;
        task.reportMarkdown = rep.reportMarkdown;
      }
      return jsonResponse(task);
    }

    // ---- POST /api/feedback ----------------------------------------------
    if (path === '/api/feedback' && method === 'POST') {
      return jsonResponse({ ok: true, queued: false, echo: 'demo' });
    }

    // ---- admin / anything else: pass through or 404 ---------------------
    if (path.startsWith('/api/')) {
      return jsonResponse(
        { code: 'DEMO_UNIMPLEMENTED', message: `Demo mode does not mock ${method} ${path}` },
        501,
      );
    }
    return null; // fall back to real fetch for non-api paths
  }

  window.fetch = async function demoFetch(input, init) {
    const path = pathFromInput(input);
    if (!path || (!path.startsWith('/api/') && path !== '/healthz')) {
      return originalFetch(input, init);
    }
    const method = methodFromInit(input, init);
    const body = init && init.body ? init.body : undefined;
    try {
      const resp = await handleRequest(path, method, body);
      if (resp) return resp;
      return originalFetch(input, init);
    } catch (err) {
      console.error('[SolGuard demo] handler error', err);
      return jsonResponse(
        { code: 'DEMO_ERROR', message: err?.message || String(err) },
        500,
      );
    }
  };

  // ============================================================
  // Submit-page prefill — lets visitors click "Start Audit → Submit"
  // and immediately press Submit without typing anything. We pre-populate
  // one Sealevel-Attacks target plus a demo email. The
  // real form validation still runs against these values, so everything
  // downstream (readTargets → POST /api/audit → shim echoes back) stays
  // consistent with what the user sees on screen.
  // ============================================================
  // GitHub values must match the frontend regex in app.js:
  //   /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/
  // i.e. exactly two path segments (owner/repo), no sub-path. Pick
  // plausible-looking owner/repo pairs so the rendered UI feels real.
  const DEMO_PREFILL_TARGETS = [
    {
      github: 'https://github.com/coral-xyz/sealevel-attacks',
      moreInfo:
        'AI-first benchmark demo · Expected: 11 Sealevel-Attacks targets, 16 findings, provenance-rich report.',
    },
  ];
  const DEMO_PREFILL_EMAIL = 'demo@solguard.xyz';

  function prefillSubmitPage() {
    const section = document.getElementById('section-submit');
    if (!section || section.classList.contains('hidden')) return;
    const list = document.getElementById('targets-list');
    if (!list) return;
    // Need at least one target card rendered by app.js first.
    const firstGithub = list.querySelector(
      'input[data-field="github"].tf-input',
    );
    if (!firstGithub) return;
    // Idempotent: once the first field is filled, never overwrite user
    // edits. Re-runs on re-entry cleanly because app.js resets the list
    // back to a single empty card on every setupSubmitSection call.
    if (firstGithub.value) return;

    // Synchronously click "Add another Audit Target" until we have 3.
    // MutationObserver callbacks are batched microtasks, so this loop
    // runs without re-entering prefillSubmitPage mid-flight.
    const addBtn = document.getElementById('btn-add-target');
    let guard = 0;
    while (
      addBtn &&
      list.querySelectorAll('.target-card').length < DEMO_PREFILL_TARGETS.length &&
      guard++ < 10
    ) {
      addBtn.click();
    }

    const cards = list.querySelectorAll('.target-card');
    DEMO_PREFILL_TARGETS.forEach((t, i) => {
      const card = cards[i];
      if (!card) return;
      Object.entries(t).forEach(([field, value]) => {
        const el = card.querySelector(
          '.tf-input[data-field="' + field + '"]',
        );
        if (!el) return;
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });

    const email = document.getElementById('input-email');
    if (email && !email.value) {
      email.value = DEMO_PREFILL_EMAIL;
      email.dispatchEvent(new Event('input', { bubbles: true }));
      email.dispatchEvent(new Event('change', { bubbles: true }));
    }
    const consent = document.getElementById('input-consent');
    if (consent && !consent.checked) consent.checked = true;

    console.info(
      '[SolGuard demo] Submit form pre-filled with',
      DEMO_PREFILL_TARGETS.length,
      'targets',
    );
  }

  function installPrefillWatcher() {
    const section = document.getElementById('section-submit');
    if (!section) return;
    // Class change on #section-submit = Router.go navigated into submit.
    new MutationObserver(prefillSubmitPage).observe(section, {
      attributes: true,
      attributeFilter: ['class'],
    });
    // childList change on #targets-list = setupSubmitSection re-rendered
    // the list. We rely on this to catch the fresh empty card and to
    // trigger the prefill after our own addBtn clicks above are processed.
    const list = document.getElementById('targets-list');
    if (list) {
      new MutationObserver(prefillSubmitPage).observe(list, {
        childList: true,
      });
    }
    // Kick once in case the page loaded directly at #submit.
    prefillSubmitPage();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', installPrefillWatcher, {
      once: true,
    });
  } else {
    installPrefillWatcher();
  }
})();
