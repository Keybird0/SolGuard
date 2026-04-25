// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// Thin fetch wrapper for the SolGuard backend. Keeps error
// handling uniform so UI callers can `try/catch` once and rely
// on { code, message } error shapes coming from the server.

const BASE = ''; // same-origin

async function jsonFetch(url, opts = {}) {
  let resp;
  try {
    resp = await fetch(BASE + url, {
      ...opts,
      headers: {
        'Content-Type': 'application/json',
        ...(opts.headers ?? {}),
      },
    });
  } catch (networkErr) {
    // Browser blocked the request / DNS failure / offline.
    const err = new Error(networkErr?.message || 'Network request failed');
    err.code = 'NETWORK_ERROR';
    err.status = 0;
    throw err;
  }
  let data = null;
  const ct = resp.headers.get('content-type') ?? '';
  if (ct.includes('application/json')) {
    data = await resp.json().catch(() => null);
  }
  // Surface the req_id the server stamped on the response — helps
  // operators trace a single bug report back to /api/admin/logs/<id>.
  const reqId = resp.headers.get('x-request-id') || undefined;
  if (!resp.ok) {
    const msg =
      (data && (data.message || data.error)) ||
      `Request failed (${resp.status})`;
    const err = new Error(msg);
    err.status = resp.status;
    err.code = data?.code || (resp.status >= 500 ? 'INTERNAL_ERROR' : undefined);
    err.details = data?.details;
    err.reqId = reqId;
    throw err;
  }
  return data;
}

export const api = {
  /** GET /healthz → { status, version, environment, checks, timestamp } */
  health: () => jsonFetch('/healthz'),

  /**
   * POST /api/audit
   * body: { targets: Target[], email }  (new P4.6 shape)
   *    or { inputs: AuditInput[], email } (legacy, wrapped server-side)
   * returns { batchId, taskIds[], status, paymentUrl?, paymentReference?,
   *           recipient?, amountSol, cluster, expiresAt?, freeAudit? }
   */
  createAudit: (body) =>
    jsonFetch('/api/audit', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** GET /api/audit/:id → full AuditTask */
  getTask: (id) => jsonFetch('/api/audit/' + encodeURIComponent(id)),

  /** GET /api/audit/batch/:id → { batch, tasks[] } */
  getBatch: (id) =>
    jsonFetch('/api/audit/batch/' + encodeURIComponent(id)),

  /**
   * POST /api/audit/:id/payment (per-task; server routes to batch if task.batchId)
   * body: { signature }
   * returns { ok, status, signature } or { ok:false, error }
   */
  pushPayment: (id, signature) =>
    jsonFetch(
      '/api/audit/' + encodeURIComponent(id) + '/payment',
      {
        method: 'POST',
        body: JSON.stringify({ signature }),
      },
    ),

  /**
   * POST /api/audit/batch/:id/payment — push one signature covering the
   * entire batch. Flips every task in the batch from paying → paid on success.
   */
  pushBatchPayment: (batchId, signature) =>
    jsonFetch(
      '/api/audit/batch/' + encodeURIComponent(batchId) + '/payment',
      {
        method: 'POST',
        body: JSON.stringify({ signature }),
      },
    ),

  /** Direct URLs for downloads / opening in new tab */
  reportMdUrl: (id) =>
    '/api/audit/' + encodeURIComponent(id) + '/report.md',
  reportJsonUrl: (id) =>
    '/api/audit/' + encodeURIComponent(id) + '/report.json',

  /** Fetch JSON report body (same as reportJsonUrl but parsed) */
  getReportJson: (id) =>
    jsonFetch('/api/audit/' + encodeURIComponent(id) + '/report.json'),

  /**
   * POST /api/feedback
   * body: { taskId?, email?, rating:1-5, content? }
   */
  feedback: (body) =>
    jsonFetch('/api/feedback', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};

/** Fetch raw Markdown body (text/markdown), falling back to task.reportMarkdown if inline. */
export async function fetchReportMd(taskId) {
  const resp = await fetch(api.reportMdUrl(taskId));
  if (!resp.ok) {
    throw new Error(`Failed to load report markdown (${resp.status})`);
  }
  return resp.text();
}
