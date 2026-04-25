// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// Main app: hash router, Toast system, section lifecycle controllers.
// Component patterns (status-badge, findings-grid, toast, progress-bar,
// fadeUp keyframe) were adapted from GoatGuard (MIT, © 2026 Keybird0);
// all business logic below is SolGuard-specific.
//
// P4.6 rewrite: Submit flow is Target-based (1..5 explicit cards, each with
// 5 fields); Progress/Report pages are batch-aware (one batchId, N sibling
// tasks rendered as per-Target rows / Target tabs).

import { api, fetchReportMd } from '/api.js';
import { friendlyError, friendlyToast } from '/errors.js';
import {
  connect as walletConnect,
  hasInjectedWallet,
  getBalanceSol,
  shortAddr,
  openPhantomInstall,
  onAccountChange,
  onDisconnect as onWalletDisconnect,
} from '/wallet.js';
import { payAudit } from '/payment.js';
import {
  renderMarkdown,
  splitReportTabs,
  downloadBlob,
  ratingFromStats,
} from '/report.js';

// ============================================================
// Global state
// ============================================================
export const State = {
  // Batch-level
  batchId: null,
  batch: null,
  tasksMap: new Map(),

  // Report page: currently selected task within the batch
  taskId: null,
  task: null,

  // Polling / wallet / UI
  pollTimer: null,
  elapsedTimer: null,
  elapsedStart: 0,
  walletAddr: null,
  walletProvider: null,

  // Report page
  reportRaw: null,
  reportTabs: null,
  currentTab: 'summary',

  submitting: false,
  paying: false,
  cluster: 'devnet',
  freeAudit: false,
  auditPriceSol: 0.01,
};

// ============================================================
// Toast
// ============================================================
export function toast(message, variant = 'info', ttlMs = 4000) {
  const wrap = document.getElementById('toast-wrap');
  if (!wrap) return;
  const el = document.createElement('div');
  el.className = 'toast ' + variant;
  el.textContent = message;
  wrap.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .3s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 300);
  }, ttlMs);
}

// ============================================================
// Router — hash-based so refresh / back preserve state.
// Format:
//   #section                      (landing / submit)
//   #section/:batchId             (progress / report / feedback — new)
//   #section/:taskId              (legacy — redirected via batch lookup)
// ============================================================
export const Router = {
  go(section, params = {}) {
    const param = params.batchId ?? params.taskId;
    const hash = param
      ? `${section}/${encodeURIComponent(param)}`
      : section;
    if (decodeURIComponent(location.hash.slice(1)) !== hash) {
      location.hash = hash;
    }
    this._activate(section, params);
  },

  _activate(section, params) {
    document.querySelectorAll('main > section').forEach((s) =>
      s.classList.add('hidden'),
    );
    const el = document.getElementById('section-' + section);
    if (!el) {
      toast('Unknown page: ' + section, 'error');
      document.getElementById('section-landing')?.classList.remove('hidden');
      return;
    }
    el.classList.remove('hidden');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    this._onLeave?.();
    this._onLeave = this.onShow[section]?.(params) || null;
  },

  parse() {
    const raw = location.hash.slice(1) || 'landing';
    const [section, ...rest] = raw.split('/');
    const param = rest.length ? decodeURIComponent(rest.join('/')) : null;
    return { section, param };
  },

  onShow: {},
  _onLeave: null,
};

window.Router = Router;
window.State = State;

// ============================================================
// SUBMIT section — N Target cards, each with 5 fields
// ============================================================

const GITHUB_RE = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/;
const SOLANA_ADDR_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
const HTTP_URL_RE = /^https?:\/\//i;

const TARGET_FIELDS = [
  {
    key: 'github',
    label: 'GitHub Repository',
    icon: '🐙',
    placeholder: 'https://github.com/owner/repo',
    type: 'url',
  },
  {
    key: 'contractAddress',
    label: 'Solana Program Address',
    icon: '🔗',
    placeholder: 'Base58 address (32–44 chars, e.g. Fg6P…sXqy)',
    type: 'text',
  },
  {
    key: 'whitepaper',
    label: 'Whitepaper URL',
    icon: '📄',
    placeholder: 'https://project.xyz/whitepaper.pdf',
    type: 'url',
  },
  {
    key: 'website',
    label: 'Project Website',
    icon: '🌐',
    placeholder: 'https://project.xyz',
    type: 'url',
  },
  {
    key: 'moreInfo',
    label: 'More Info',
    icon: '📝',
    placeholder:
      'Anything else the auditor should know (free text, up to 2000 characters).',
    type: 'textarea',
  },
];

function createTargetCard(n) {
  const card = document.createElement('div');
  card.className = 'target-card';
  card.dataset.idx = String(n);

  const fieldRows = TARGET_FIELDS.map((f) => {
    const id = `t-${n}-${f.key}`;
    if (f.type === 'textarea') {
      return `
        <div class="target-field-row" data-field="${f.key}">
          <label for="${id}" class="tf-label">
            <span class="tf-icon">${f.icon}</span>
            ${f.label}
            <span class="tf-meta">
              <span class="tf-counter" data-counter="${f.key}">0</span>/2000
            </span>
          </label>
          <textarea
            id="${id}"
            class="input tf-input"
            data-field="${f.key}"
            placeholder="${f.placeholder}"
            maxlength="2000"
            rows="3"
          ></textarea>
          <div class="tf-error" hidden></div>
        </div>
      `;
    }
    return `
      <div class="target-field-row" data-field="${f.key}">
        <label for="${id}" class="tf-label">
          <span class="tf-icon">${f.icon}</span>
          ${f.label}
        </label>
        <input
          id="${id}"
          class="input tf-input"
          type="${f.type}"
          data-field="${f.key}"
          placeholder="${f.placeholder}"
          autocomplete="off"
          spellcheck="false"
        />
        <div class="tf-error" hidden></div>
      </div>
    `;
  }).join('');

  card.innerHTML = `
    <div class="target-header">
      <span class="target-badge">Audit Target #${n}</span>
      <button type="button" class="target-del" title="Remove this Target" aria-label="Remove Target">
        ×
      </button>
    </div>
    <div class="target-fields">${fieldRows}</div>
  `;

  card.querySelector('.target-del').addEventListener('click', () => {
    removeTargetCard(card);
  });

  // Live character counter for moreInfo
  const moreInfo = card.querySelector('textarea[data-field="moreInfo"]');
  const counter = card.querySelector('[data-counter="moreInfo"]');
  if (moreInfo && counter) {
    moreInfo.addEventListener('input', () => {
      counter.textContent = String(moreInfo.value.length);
    });
  }

  return card;
}

function renumberTargetCards() {
  const list = document.getElementById('targets-list');
  const cards = list.querySelectorAll('.target-card');
  cards.forEach((card, i) => {
    const n = i + 1;
    card.dataset.idx = String(n);
    card.querySelector('.target-badge').textContent = `Audit Target #${n}`;
    // rewrite the `id` / `for` pairs so labels stay clickable
    TARGET_FIELDS.forEach((f) => {
      const label = card.querySelector(`.target-field-row[data-field="${f.key}"] label`);
      const input = card.querySelector(`.target-field-row[data-field="${f.key}"] .tf-input`);
      const id = `t-${n}-${f.key}`;
      if (label) label.setAttribute('for', id);
      if (input) input.id = id;
    });
  });
  // Show/hide delete button based on whether there's >1 card
  cards.forEach((card) => {
    const del = card.querySelector('.target-del');
    if (del) del.style.visibility = cards.length > 1 ? 'visible' : 'hidden';
  });
  updatePriceBadge();
}

function addTargetCard() {
  const list = document.getElementById('targets-list');
  const count = list.querySelectorAll('.target-card').length;
  if (count >= 5) {
    toast('Up to 5 Audit Targets per submission.', 'info');
    return;
  }
  list.appendChild(createTargetCard(count + 1));
  renumberTargetCards();
}

function removeTargetCard(card) {
  const list = document.getElementById('targets-list');
  if (list.querySelectorAll('.target-card').length <= 1) return;
  card.remove();
  renumberTargetCards();
}

function readTargets() {
  const cards = document.querySelectorAll('#targets-list .target-card');
  const targets = [];
  cards.forEach((card) => {
    const t = {};
    TARGET_FIELDS.forEach((f) => {
      const el = card.querySelector(`.tf-input[data-field="${f.key}"]`);
      const v = (el?.value ?? '').trim();
      if (v) t[f.key] = v;
    });
    targets.push(t);
  });
  return targets;
}

function validateTarget(t, idx) {
  const errs = [];
  const primaryCount =
    (t.github ? 1 : 0) +
    (t.contractAddress ? 1 : 0) +
    (t.whitepaper ? 1 : 0) +
    (t.website ? 1 : 0);
  if (primaryCount === 0) {
    errs.push({
      field: null,
      msg: `Audit Target #${idx + 1}: please fill at least one of GitHub / Program Address / Whitepaper / Website.`,
    });
  }
  if (t.github && !GITHUB_RE.test(t.github)) {
    errs.push({ field: 'github', msg: 'Expected https://github.com/owner/repo' });
  }
  if (t.contractAddress && !SOLANA_ADDR_RE.test(t.contractAddress)) {
    errs.push({
      field: 'contractAddress',
      msg: 'Expected base58 Solana address (32–44 chars).',
    });
  }
  if (t.whitepaper && !HTTP_URL_RE.test(t.whitepaper)) {
    errs.push({ field: 'whitepaper', msg: 'Expected a http(s) URL.' });
  }
  if (t.website && !HTTP_URL_RE.test(t.website)) {
    errs.push({ field: 'website', msg: 'Expected a http(s) URL.' });
  }
  if (t.moreInfo && t.moreInfo.length > 2000) {
    errs.push({
      field: 'moreInfo',
      msg: 'More Info must be 2000 characters or fewer.',
    });
  }
  return errs;
}

function validateEmail(v) {
  if (!v) return 'Email required';
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return 'Invalid email format';
  return null;
}

function updatePriceBadge() {
  const list = document.getElementById('targets-list');
  if (!list) return;
  const n = list.querySelectorAll('.target-card').length || 1;
  const unit = State.auditPriceSol;
  const total = +(n * unit).toFixed(9);
  document.getElementById('ps-count').textContent = String(n);
  document.getElementById('ps-unit').textContent = unit.toString();
  document.getElementById('ps-total').textContent = State.freeAudit
    ? '0'
    : total.toString();
  if (State.freeAudit) {
    document.getElementById('ps-breakdown').innerHTML =
      `<span id="ps-count">${n}</span> Target${n > 1 ? 's' : ''} · Free audit mode`;
  }
}

function clearTargetErrors() {
  document
    .querySelectorAll('#targets-list .tf-input')
    .forEach((el) => el.classList.remove('input-error'));
  document
    .querySelectorAll('#targets-list .tf-error')
    .forEach((el) => {
      el.hidden = true;
      el.textContent = '';
    });
}

function applyTargetErrors(card, errs) {
  errs.forEach(({ field, msg }) => {
    if (!field) {
      // Card-level error: attach to the header area via a banner on the
      // first field row.
      const first = card.querySelector('.target-field-row');
      if (first) {
        let errEl = first.querySelector('.tf-error');
        if (errEl) {
          errEl.hidden = false;
          errEl.textContent = msg;
        }
      }
      return;
    }
    const row = card.querySelector(`.target-field-row[data-field="${field}"]`);
    if (!row) return;
    const input = row.querySelector('.tf-input');
    const errEl = row.querySelector('.tf-error');
    if (input) input.classList.add('input-error');
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = msg;
    }
  });
}

function setupSubmitSection() {
  const list = document.getElementById('targets-list');
  list.innerHTML = '';
  list.appendChild(createTargetCard(1));
  renumberTargetCards();

  document.getElementById('btn-add-target').onclick = addTargetCard;

  const form = document.getElementById('submit-form');
  form.onsubmit = async (e) => {
    e.preventDefault();
    if (State.submitting) return;

    const targets = readTargets();
    const emailEl = document.getElementById('input-email');
    const email = emailEl.value.trim();
    const consent = document.getElementById('input-consent').checked;

    clearTargetErrors();
    const errEmail = document.getElementById('err-email');
    errEmail.hidden = true;
    errEmail.textContent = '';
    emailEl.classList.remove('input-error');

    if (targets.length === 0 || targets.length > 5) {
      toast('Provide 1–5 Audit Targets.', 'error');
      return;
    }

    let hadError = false;
    const cards = document.querySelectorAll('#targets-list .target-card');
    targets.forEach((t, i) => {
      const errs = validateTarget(t, i);
      if (errs.length) {
        hadError = true;
        applyTargetErrors(cards[i], errs);
      }
    });

    const emailErr = validateEmail(email);
    if (emailErr) {
      hadError = true;
      errEmail.hidden = false;
      errEmail.textContent = emailErr;
      emailEl.classList.add('input-error');
    }

    if (!consent) {
      toast('Please confirm the consent checkbox.', 'error');
      return;
    }
    if (hadError) {
      toast('Please fix the highlighted fields.', 'error');
      return;
    }

    State.submitting = true;
    const btn = document.getElementById('btn-submit');
    const oldLabel = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Submitting…';

    try {
      const resp = await api.createAudit({ targets, email });
      State.batchId = resp.batchId;
      State.batch = resp;
      toast(
        resp.taskIds?.length > 1
          ? `Batch created with ${resp.taskIds.length} audit tasks.`
          : 'Audit created.',
        'success',
      );
      Router.go('progress', { batchId: resp.batchId });
    } catch (err) {
      console.error(err);
      toast(friendlyToast(err), 'error', 6000);
    } finally {
      State.submitting = false;
      btn.disabled = false;
      btn.innerHTML = oldLabel;
    }
  };

  updatePriceBadge();
}

Router.onShow.submit = () => {
  setupSubmitSection();
  // Soft auto-focus for the first reasonable input so keyboard users
  // can start typing immediately. We target the first empty GitHub
  // URL field — falling back to the email input if all targets are
  // already populated (e.g. form restored from history).
  setTimeout(() => {
    const firstEmptyInput = document.querySelector(
      '#targets-list input[data-field="github"]:placeholder-shown',
    );
    (firstEmptyInput || document.getElementById('input-email'))?.focus();
  }, 60);
  return null;
};

// ============================================================
// PROGRESS section — batch payment + per-target progress
// ============================================================
function setStatusBadge(el, status) {
  if (!el) return;
  el.className = 'status-badge status-' + status;
  el.textContent = prettyStatus(status);
}

function prettyStatus(s) {
  return (
    {
      pending: 'Pending',
      paying: 'Awaiting payment',
      paid: 'Paid — queued',
      scanning: 'Scanning',
      analyzing: 'AI analysis',
      reporting: 'Composing report',
      completed: 'Completed',
      failed: 'Failed',
    }[s] || s
  );
}

function guessPct(status) {
  return (
    {
      pending: 3,
      paying: 3,
      paid: 10,
      scanning: 40,
      analyzing: 70,
      reporting: 90,
      completed: 100,
      failed: 100,
    }[status] || 10
  );
}

function shortValue(v) {
  if (!v) return '';
  if (v.length <= 36) return v;
  return v.slice(0, 20) + '…' + v.slice(-10);
}

function targetSummary(task, idx) {
  const primary = (task.inputs || []).find(
    (i) => i.type !== 'more_info',
  );
  if (!primary) return `Target #${idx + 1}`;
  const kindLabel = {
    github: 'GitHub',
    contract_address: 'Program',
    whitepaper: 'Whitepaper',
    website: 'Website',
  }[primary.type] || primary.type;
  return `${kindLabel}: ${shortValue(primary.value)}`;
}

function ensureTaskRow(task, idx) {
  const list = document.getElementById('task-list');
  let row = list.querySelector(`.task-row[data-id="${task.taskId}"]`);
  if (!row) {
    row = document.createElement('div');
    row.className = 'task-row';
    row.dataset.id = task.taskId;
    row.innerHTML = `
      <div class="tr-head">
        <span class="tr-idx">#${idx + 1}</span>
        <span class="tr-summary"></span>
        <span class="status-badge tr-status">Queued</span>
        <span class="small muted tr-pct">0%</span>
      </div>
      <div class="progress-bar"><div class="fill tr-fill"></div></div>
      <div class="tr-text small muted">—</div>
    `;
    list.appendChild(row);
  }
  return row;
}

function renderBatchProgress(batch, tasks) {
  State.batch = batch;
  State.tasksMap = new Map(tasks.map((t) => [t.taskId, t]));

  const payPane = document.getElementById('pay-pane');
  const auditPane = document.getElementById('audit-pane');
  const failPane = document.getElementById('fail-pane');

  if (batch.status === 'failed') {
    payPane.hidden = true;
    auditPane.hidden = true;
    failPane.hidden = false;
    // Prefer the first surfaced task error so operators see the real
    // underlying failure instead of the generic batch-level one.
    const firstFailedTask = tasks.find((t) => t.error);
    const reason =
      firstFailedTask?.error ||
      batch.error ||
      'The batch failed. Check each Target card below for details.';
    document.getElementById('fail-reason').textContent = reason;
    stopPolling();
    return;
  }

  if (batch.status === 'paying') {
    payPane.hidden = false;
    auditPane.hidden = true;
    failPane.hidden = true;
    document.getElementById('prog-title').textContent =
      tasks.length > 1
        ? `Pay to start ${tasks.length} audits`
        : 'Pay to start your audit';
    document.getElementById('prog-subtitle').textContent =
      'Your batch has been created. Pay with Phantom to unlock every audit at once.';
    document.getElementById('pay-taskid').textContent = batch.batchId;
    document.getElementById('pay-target-count').textContent = String(tasks.length);
    document.getElementById('pay-cluster').textContent =
      batch.cluster || State.cluster || 'devnet';
    const amt = batch.totalAmountSol ?? 0;
    document.getElementById('pay-amount').textContent = amt.toString();
    document.getElementById('pay-btn-amount').textContent = amt.toString();
    const breakdown = document.getElementById('pay-amount-breakdown');
    if (breakdown) {
      breakdown.textContent =
        tasks.length > 1
          ? `(${tasks.length} × ${State.auditPriceSol} SOL)`
          : '';
    }
    document.getElementById('pay-recipient').textContent = shortAddr(
      batch.paymentRecipient,
    );
    document.getElementById('pay-reference').textContent = shortAddr(
      batch.paymentReference,
    );
    return;
  }

  // batch.status === 'paid' — render per-task rows
  payPane.hidden = true;
  auditPane.hidden = false;
  failPane.hidden = true;
  document.getElementById('prog-title').textContent =
    tasks.length > 1
      ? `Auditing your ${tasks.length} Targets…`
      : 'Auditing your program…';
  document.getElementById('prog-subtitle').textContent =
    'Keep this tab open — refresh keeps your place.';

  document.getElementById('audit-total-count').textContent = String(tasks.length);

  const list = document.getElementById('task-list');
  // Reorder DOM if task list changed
  const existing = new Set(Array.from(list.children).map((c) => c.dataset.id));
  tasks.forEach((task, idx) => {
    const row = ensureTaskRow(task, idx);
    row.querySelector('.tr-idx').textContent = `#${idx + 1}`;
    row.querySelector('.tr-summary').textContent = targetSummary(task, idx);
    setStatusBadge(row.querySelector('.tr-status'), task.status);
    const pct = task.status === 'completed'
      ? 100
      : task.status === 'failed'
      ? 100
      : Math.min(Math.max(task.progressPercent ?? guessPct(task.status), 5), 99);
    row.querySelector('.tr-fill').style.width = pct + '%';
    row.querySelector('.tr-pct').textContent = pct + '%';
    row.querySelector('.tr-text').textContent =
      task.error ? `Error: ${task.error}` : (task.progress || prettyStatus(task.status));
    row.classList.toggle('row-failed', task.status === 'failed');
    row.classList.toggle('row-completed', task.status === 'completed');
    existing.delete(task.taskId);
  });
  // Drop rows whose task disappeared (shouldn't happen, but be defensive)
  existing.forEach((id) => {
    const node = list.querySelector(`.task-row[data-id="${id}"]`);
    node?.remove();
  });

  const completed = tasks.filter((t) => t.status === 'completed').length;
  const failedCount = tasks.filter((t) => t.status === 'failed').length;
  const anyInFlight = tasks.some(
    (t) => t.status !== 'completed' && t.status !== 'failed',
  );

  const totalPct = Math.round(
    tasks.reduce((acc, t) => {
      if (t.status === 'completed') return acc + 100;
      if (t.status === 'failed') return acc + 100;
      return (
        acc + Math.min(Math.max(t.progressPercent ?? guessPct(t.status), 5), 99)
      );
    }, 0) / Math.max(tasks.length, 1),
  );
  document.getElementById('audit-overall-pct').textContent = totalPct + '%';
  document.getElementById('audit-overall-fill').style.width = totalPct + '%';
  document.getElementById('audit-completed-count').textContent = String(completed);

  let overallStatus = 'paid';
  if (completed === tasks.length) overallStatus = 'completed';
  else if (!anyInFlight && failedCount > 0) overallStatus = 'failed';
  else if (tasks.some((t) => t.status === 'reporting')) overallStatus = 'reporting';
  else if (tasks.some((t) => t.status === 'analyzing')) overallStatus = 'analyzing';
  else if (tasks.some((t) => t.status === 'scanning')) overallStatus = 'scanning';
  setStatusBadge(document.getElementById('audit-status'), overallStatus);
  document.getElementById('audit-overall-text').textContent =
    overallStatus === 'completed'
      ? 'All Targets audited — loading reports…'
      : overallStatus === 'failed'
      ? 'Some Targets failed; see per-Target details below.'
      : 'Running Solana audit pipeline per Target…';

  if (completed === tasks.length) {
    stopPolling();
    toast(
      tasks.length > 1 ? 'All audits complete!' : 'Audit complete!',
      'success',
    );
    Router.go('report', { batchId: batch.batchId });
  } else if (!anyInFlight && failedCount === tasks.length) {
    stopPolling();
  }
}

function startPolling(batchId) {
  stopPolling();
  State.elapsedStart = Date.now();
  State.elapsedTimer = setInterval(() => {
    const secs = Math.round((Date.now() - State.elapsedStart) / 1000);
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    const el = document.getElementById('audit-elapsed');
    if (el) el.textContent = m > 0 ? `${m}m ${s}s` : `${s}s`;
  }, 1000);

  const tick = async () => {
    try {
      const resp = await api.getBatch(batchId);
      renderBatchProgress(resp.batch, resp.tasks || []);
    } catch (err) {
      console.warn('poll failed:', err);
    }
  };
  tick();
  State.pollTimer = setInterval(tick, 2000);
}

function stopPolling() {
  if (State.pollTimer) clearInterval(State.pollTimer);
  if (State.elapsedTimer) clearInterval(State.elapsedTimer);
  State.pollTimer = null;
  State.elapsedTimer = null;
}

async function refreshWalletBalance() {
  if (!State.walletAddr) return;
  try {
    const bal = await getBalanceSol(State.walletAddr);
    document.getElementById('wallet-balance').textContent =
      bal.toFixed(4) + ' SOL';
  } catch {
    document.getElementById('wallet-balance').textContent = '—';
  }
}

async function handleConnectWallet() {
  if (!hasInjectedWallet()) {
    toast('Phantom not detected. Opening install page…', 'info');
    openPhantomInstall();
    return;
  }
  try {
    const { publicKey, provider } = await walletConnect();
    State.walletAddr = publicKey;
    State.walletProvider = provider;
    document.getElementById('wallet-disconnected').hidden = true;
    document.getElementById('wallet-connected').hidden = false;
    document.getElementById('wallet-addr').textContent = shortAddr(publicKey);
    await refreshWalletBalance();
    toast('Wallet connected: ' + shortAddr(publicKey), 'success');

    onAccountChange((pub) => {
      if (!pub) {
        resetWalletUI();
      } else {
        State.walletAddr = pub;
        document.getElementById('wallet-addr').textContent = shortAddr(pub);
        refreshWalletBalance();
      }
    });
    onWalletDisconnect(() => resetWalletUI());
  } catch (err) {
    console.error(err);
    toast(friendlyToast(err), 'error', 6000);
  }
}

function resetWalletUI() {
  State.walletAddr = null;
  State.walletProvider = null;
  document.getElementById('wallet-disconnected').hidden = false;
  document.getElementById('wallet-connected').hidden = true;
}

async function handlePay() {
  if (!State.batch || !State.walletProvider || !State.walletAddr) return;
  if (State.paying) return;

  const batch = State.batch;
  const recipient = batch.paymentRecipient;
  const amountSol = batch.totalAmountSol;
  const reference = batch.paymentReference;
  if (!recipient || !reference || !amountSol) {
    toast('Missing payment parameters from server', 'error');
    return;
  }

  State.paying = true;
  const btn = document.getElementById('btn-pay');
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Confirm in wallet…';

  try {
    const signature = await payAudit({
      provider: State.walletProvider,
      userPubkey: State.walletAddr,
      recipient,
      amountSol,
      reference,
      onSignatureBroadcast: (sig) => {
        btn.innerHTML = '<span class="spinner"></span> Waiting for confirmation…';
        document.getElementById('tx-pending').hidden = false;
        document.getElementById('tx-sig').textContent = shortAddr(sig);
      },
    });

    toast('Transaction confirmed. Verifying on server…', 'info');
    try {
      const pushResp = await api.pushBatchPayment(batch.batchId, signature);
      if (pushResp?.ok) {
        toast('Payment verified. Audits starting…', 'success');
      } else {
        toast(
          'Server still validating payment — audits will start shortly.',
          'info',
        );
      }
    } catch (e) {
      console.warn('pushBatchPayment failed', e);
      toast(
        'Could not push signature to server; the background poller will retry.',
        'info',
      );
    }

    // Nudge UI to the in-flight view immediately; the poller will catch up.
    State.batch = {
      ...State.batch,
      status: 'paid',
      paymentSignature: signature,
    };
  } catch (err) {
    console.error(err);
    toast(friendlyToast(err), 'error', 6000);
    btn.disabled = false;
    btn.innerHTML = old;
  } finally {
    State.paying = false;
    document.getElementById('tx-pending').hidden = true;
  }
}

async function handleManualSignature() {
  const input = document.getElementById('input-manual-sig');
  const sig = input.value.trim();
  if (!sig) {
    toast('Paste a transaction signature first', 'error');
    return;
  }
  if (!State.batch?.batchId) return;
  try {
    const resp = await api.pushBatchPayment(State.batch.batchId, sig);
    if (resp?.ok) {
      toast('Signature accepted', 'success');
      document.getElementById('manual-sig-pane').hidden = true;
    } else {
      toast(
        'Server could not verify: ' + (resp?.error || 'unknown'),
        'error',
      );
    }
  } catch (e) {
    toast(friendlyToast(e), 'error', 6000);
  }
}

/**
 * Resolve a URL parameter to a batchId. Tries /api/audit/batch/:id first
 * (new shape), then falls back to /api/audit/:id for legacy taskId links
 * and, if the task carries a batchId, rewrites the browser hash so the
 * bookmark is upgraded on-the-fly.
 *
 * Returns:
 *   { batchId }          — good to go
 *   { redirected: true } — resolveBatchParam already pushed a new hash, caller should abort
 *   { error: ... }       — nothing found
 */
async function resolveBatchParam(param, targetSection) {
  if (!param) return { error: 'no-param' };
  try {
    const b = await api.getBatch(param);
    if (b?.batch?.batchId) return { batchId: b.batch.batchId };
  } catch (err) {
    if (err?.status !== 404) throw err;
  }
  try {
    const task = await api.getTask(param);
    if (task?.batchId) {
      toast('Updating link to batch view…', 'info');
      Router.go(targetSection, { batchId: task.batchId });
      return { redirected: true };
    }
    return { error: 'no-batch' };
  } catch {
    return { error: 'not-found' };
  }
}

Router.onShow.progress = async (params) => {
  const param = params?.batchId ?? params?.taskId ?? params?.param;
  if (!param) {
    toast('No audit selected', 'info');
    Router.go('submit');
    return null;
  }

  const resolved = await resolveBatchParam(param, 'progress');
  if (resolved.redirected) return null;
  if (!resolved.batchId) {
    toast('Could not load audit status.', 'error');
    Router.go('submit');
    return null;
  }
  const batchId = resolved.batchId;
  State.batchId = batchId;

  // Reset panes
  document.getElementById('wallet-disconnected').hidden = Boolean(State.walletAddr);
  document.getElementById('wallet-connected').hidden = !State.walletAddr;
  document.getElementById('tx-pending').hidden = true;
  document.getElementById('manual-sig-pane').hidden = true;
  document.getElementById('task-list').innerHTML = '';

  document.getElementById('btn-connect').onclick = handleConnectWallet;
  document.getElementById('btn-pay').onclick = handlePay;
  document.getElementById('btn-manual-sig').onclick = (e) => {
    e.preventDefault();
    const pane = document.getElementById('manual-sig-pane');
    pane.hidden = !pane.hidden;
    if (!pane.hidden) {
      // Move focus into the freshly revealed input so keyboard users
      // don't have to tab hunt.
      setTimeout(
        () => document.getElementById('input-manual-sig')?.focus(),
        0,
      );
    }
  };
  document.getElementById('btn-push-manual').onclick = handleManualSignature;
  // Enter-to-submit inside the manual signature field.
  document.getElementById('input-manual-sig')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleManualSignature();
    }
  });
  // "Copy reference" for operators who want to tail the batch
  // off-site (Explorer search, Slack, etc.).
  document.getElementById('btn-copy-reference')?.addEventListener('click', async () => {
    const ref = State.batch?.paymentReference;
    if (!ref) return;
    try {
      await navigator.clipboard.writeText(ref);
      toast('Reference copied to clipboard.', 'success', 2500);
    } catch {
      // Fallback — just show the full ref so the user can copy manually.
      toast(ref, 'info', 6000);
    }
  });

  startPolling(batchId);
  return () => stopPolling();
};

// ============================================================
// REPORT section
// ============================================================
function setActiveTab(name) {
  State.currentTab = name;
  document
    .querySelectorAll('#section-report .report-tabs .tab')
    .forEach((t) => {
      t.classList.toggle('active', t.dataset.tab === name);
    });
  const body = document.getElementById('rep-body');
  const tabs = State.reportTabs || splitReportTabs(State.reportRaw || '');
  const md = tabs[name] || '';
  if (!md.trim()) {
    body.innerHTML =
      '<p class="muted small">This section is empty for this audit.</p>';
    return;
  }
  renderMarkdown(body, md);
}

function renderFindingsSidebar(findings) {
  const ul = document.getElementById('findings-side');
  ul.innerHTML = '';
  if (!findings?.length) {
    const li = document.createElement('li');
    li.className = 'muted small';
    li.textContent = 'No findings to show.';
    ul.appendChild(li);
    return;
  }
  const order = ['Critical', 'High', 'Medium', 'Low', 'Info'];
  const sorted = [...findings].sort(
    (a, b) => order.indexOf(a.severity) - order.indexOf(b.severity),
  );
  sorted.forEach((f) => {
    const li = document.createElement('li');
    li.innerHTML = `
      <span class="sev-dot ${f.severity}" aria-hidden="true"></span>
      <span>${escapeHtml(f.title || f.id)}</span>
    `;
    li.title = `${f.severity} · ${f.location || ''}`;
    li.addEventListener('click', () => {
      const id = slugify(f.title || f.id);
      const target = document
        .getElementById('rep-body')
        ?.querySelector(`#${CSS.escape(id)}`);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
    ul.appendChild(li);
  });
}

function slugify(s) {
  return (
    (s || '')
      .toString()
      .toLowerCase()
      .trim()
      .replace(/[^\w\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-') || 'finding'
  );
}
function escapeHtml(s) {
  return String(s ?? '').replace(
    /[&<>"']/g,
    (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[
        c
      ],
  );
}

function renderTargetTabs(tasks, activeTaskId) {
  const wrap = document.getElementById('target-tabs');
  wrap.innerHTML = '';
  if (!tasks || tasks.length <= 1) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  tasks.forEach((task, idx) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'target-tab';
    btn.classList.toggle('active', task.taskId === activeTaskId);
    btn.classList.toggle('tab-failed', task.status === 'failed');
    btn.innerHTML = `
      <span class="tt-idx">#${idx + 1}</span>
      <span class="tt-label">${escapeHtml(targetSummary(task, idx))}</span>
    `;
    btn.onclick = () => {
      State.taskId = task.taskId;
      State.task = task;
      renderTargetTabs(tasks, task.taskId);
      hydrateTask(task.taskId);
    };
    wrap.appendChild(btn);
  });
}

async function hydrateTask(taskId) {
  const body = document.getElementById('rep-body');
  body.innerHTML = '<p class="muted small">Loading report…</p>';
  try {
    const [task, md] = await Promise.all([
      api.getTask(taskId),
      fetchReportMd(taskId).catch(() => null),
    ]);
    State.task = task;
    State.taskId = taskId;
    State.reportRaw = md || task.reportMarkdown || '';
    State.reportTabs = splitReportTabs(State.reportRaw);

    const title = task.inputs?.[0]?.value
      ? 'Audit · ' + shortValue(task.inputs[0].value)
      : 'Audit Report';
    document.getElementById('rep-title').textContent = title;
    document.getElementById('rep-taskid').textContent = task.taskId;
    document.getElementById('rep-completed').textContent = task.completedAt
      ? new Date(task.completedAt).toLocaleString()
      : '—';

    const stats = task.statistics || {};
    document.getElementById('count-critical').textContent = stats.critical ?? 0;
    document.getElementById('count-high').textContent = stats.high ?? 0;
    document.getElementById('count-medium').textContent = stats.medium ?? 0;
    document.getElementById('count-low').textContent = stats.low ?? 0;
    document.getElementById('count-info').textContent = stats.info ?? 0;

    const rating = ratingFromStats(stats);
    const rEl = document.getElementById('rep-rating');
    rEl.textContent = rating;
    rEl.className = 'rating rating-' + rating;

    renderFindingsSidebar(task.findings);
    setActiveTab(State.currentTab || 'summary');
  } catch (err) {
    console.error(err);
    body.innerHTML =
      '<p class="error">Could not load report: ' +
      escapeHtml(err.message) +
      '</p>';
  }
}

async function hydrateReport(batchId) {
  try {
    const { batch, tasks } = await api.getBatch(batchId);
    State.batchId = batchId;
    State.batch = batch;
    State.tasksMap = new Map(tasks.map((t) => [t.taskId, t]));

    const completed = tasks.filter((t) => t.status === 'completed');
    const first = completed[0] || tasks[0];
    State.taskId = first?.taskId || null;
    renderTargetTabs(tasks, State.taskId);
    if (State.taskId) {
      await hydrateTask(State.taskId);
    } else {
      document.getElementById('rep-body').innerHTML =
        '<p class="muted small">No completed task to display yet.</p>';
    }
  } catch (err) {
    console.error(err);
    document.getElementById('rep-body').innerHTML =
      '<p class="error">Could not load batch: ' + escapeHtml(err.message) + '</p>';
  }
}

Router.onShow.report = async (params) => {
  const param = params?.batchId ?? params?.taskId ?? params?.param;
  if (!param) {
    Router.go('landing');
    return null;
  }

  const resolved = await resolveBatchParam(param, 'report');
  if (resolved.redirected) return null;
  if (!resolved.batchId) {
    toast('Could not load audit report.', 'error');
    Router.go('landing');
    return null;
  }
  const batchId = resolved.batchId;

  State.batchId = batchId;
  State.currentTab = 'summary';

  document.querySelectorAll('#section-report .report-tabs .tab').forEach((t) => {
    t.onclick = () => setActiveTab(t.dataset.tab);
  });
  document.getElementById('btn-dl-md').onclick = async () => {
    const id = State.taskId;
    if (!id) return toast('No Target selected', 'info');
    try {
      const md = State.reportRaw || (await fetchReportMd(id));
      downloadBlob({
        text: md,
        filename: `solguard-${id}.md`,
        mime: 'text/markdown;charset=utf-8',
      });
    } catch {
      toast('Could not download markdown', 'error');
    }
  };
  document.getElementById('btn-dl-json').onclick = async () => {
    const id = State.taskId;
    if (!id) return toast('No Target selected', 'info');
    try {
      const json = await api.getReportJson(id);
      downloadBlob({
        text: JSON.stringify(json, null, 2),
        filename: `solguard-${id}.json`,
        mime: 'application/json;charset=utf-8',
      });
    } catch {
      toast('Could not download JSON', 'error');
    }
  };
  document.getElementById('btn-print').onclick = () => window.print();

  hydrateReport(batchId);
  return null;
};

// ============================================================
// FEEDBACK section
// ============================================================
function setupStars() {
  const wrap = document.getElementById('fb-stars');
  wrap.innerHTML = '';
  for (let i = 1; i <= 5; i++) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'star';
    b.dataset.value = String(i);
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-label', `${i} star${i > 1 ? 's' : ''}`);
    b.textContent = '★';
    b.onclick = () => setRating(i);
    wrap.appendChild(b);
  }
}
function setRating(n) {
  document.getElementById('fb-rating').value = String(n);
  document.querySelectorAll('#fb-stars .star').forEach((el, i) => {
    el.classList.toggle('active', i < n);
  });
  document.getElementById('err-rating').hidden = true;
}

Router.onShow.feedback = (params) => {
  setupStars();
  setRating(0);

  // Accept either batchId or taskId; feedback itself is still per-task
  // on the server side. If we have a batchId + currently-open task, use
  // that task; otherwise fall back to whichever param was provided.
  const taskId = State.taskId || params?.taskId || null;

  const form = document.getElementById('feedback-form');
  const thanks = document.getElementById('fb-thanks');
  form.hidden = false;
  thanks.hidden = true;

  form.onsubmit = async (e) => {
    e.preventDefault();
    const rating = Number(document.getElementById('fb-rating').value);
    if (!rating) {
      document.getElementById('err-rating').hidden = false;
      return;
    }
    const content = document.getElementById('fb-content').value.trim();
    const email = document.getElementById('fb-email').value.trim();
    const btn = document.getElementById('btn-fb-submit');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Sending…';
    try {
      await api.feedback({
        taskId: taskId || undefined,
        rating,
        content: content || undefined,
        email: email || undefined,
      });
      form.hidden = true;
      thanks.hidden = false;
      toast('Thanks for the feedback!', 'success');
    } catch (err) {
      toast(friendlyToast(err), 'error', 6000);
      btn.disabled = false;
      btn.innerHTML = 'Send Feedback';
    }
  };
  return null;
};

// ============================================================
// LANDING — noop but present to avoid cleanup issues
// ============================================================
Router.onShow.landing = () => null;

// ============================================================
// Bootstrap
// ============================================================
async function bootstrap() {
  // health → pick up FREE_AUDIT + cluster + price to tweak UI
  try {
    const h = await api.health();
    State.cluster = h.checks?.solanaCluster || 'devnet';
    State.freeAudit = Boolean(h.checks?.freeAudit);
    if (typeof h.checks?.auditPriceSol === 'number') {
      State.auditPriceSol = h.checks.auditPriceSol;
    }
    const chip = document.getElementById('cluster-chip');
    if (chip) {
      chip.textContent = State.cluster;
      chip.classList.toggle('devnet', State.cluster !== 'mainnet-beta');
    }
    if (State.freeAudit) {
      document.querySelector('.hero .stats')?.insertAdjacentHTML(
        'beforeend',
        '<span>🎁 <b>Free</b> · no payment required</span>',
      );
    }
  } catch {
    /* server might be starting up; UI still works */
  }

  const { section, param } = Router.parse();
  Router._activate(section, { param });
  window.addEventListener('hashchange', () => {
    const p = Router.parse();
    Router._activate(p.section, { param: p.param });
  });
}

bootstrap();
