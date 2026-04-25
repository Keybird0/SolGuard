// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// Report rendering: lazy-loads marked.js + highlight.js from CDN (only
// when the user first opens the Report section), renders the audit
// Markdown into .md-body, and provides Blob-based downloads for .md/.json.

const MARKED_SRC = 'https://cdn.jsdelivr.net/npm/marked@11.2.0/marked.min.js';
const HLJS_SRC =
  'https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/lib/common.min.js';
const HLJS_CSS =
  'https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github-dark.min.css';

let markedPromise = null;
let hljsPromise = null;

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
function loadCss(href) {
  return new Promise((resolve) => {
    const l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = href;
    l.onload = () => resolve();
    l.onerror = () => resolve();
    document.head.appendChild(l);
  });
}

async function ensureMarked() {
  if (window.marked) return window.marked;
  if (!markedPromise) markedPromise = loadScript(MARKED_SRC);
  await markedPromise;
  return window.marked;
}

async function ensureHljs() {
  if (window.hljs) return window.hljs;
  if (!hljsPromise) {
    hljsPromise = Promise.all([loadScript(HLJS_SRC), loadCss(HLJS_CSS)]);
  }
  await hljsPromise;
  return window.hljs;
}

/** Render markdown into an element; runs highlight.js after inject. */
export async function renderMarkdown(target, markdown) {
  const marked = await ensureMarked();
  const hljs = await ensureHljs().catch(() => null);

  marked.setOptions({ gfm: true, breaks: false });
  target.innerHTML = marked.parse(markdown ?? '');

  // marked v11 removed the `headerIds` option — add IDs ourselves so
  // the findings sidebar can scroll-to-heading via anchor.
  target.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach((h) => {
    if (!h.id) h.id = slugify(h.textContent || '');
  });

  if (hljs) {
    target.querySelectorAll('pre code').forEach((el) => {
      try {
        hljs.highlightElement(el);
      } catch {
        /* ignore */
      }
    });
  }
}

function slugify(s) {
  return (
    (s || '')
      .toString()
      .toLowerCase()
      .trim()
      .replace(/[^\w\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-') || 'section'
  );
}

/**
 * Split the full report into logical "tabs" by top-level H1/H2 boundaries.
 * The skill's three-tier report uses predictable section headings; we
 * fall back to "full" if we can't find them so the user still sees
 * something.
 */
export function splitReportTabs(md) {
  if (!md) return { summary: '', assessment: '', checklist: '' };

  const lower = md.toLowerCase();
  const pick = (start, end) => {
    if (start < 0) return '';
    return end >= 0 ? md.slice(start, end) : md.slice(start);
  };
  // look for the common headings emitted by `tools/solana_report.py`
  const iSummary = findHeading(lower, ['risk summary', 'risk-summary']);
  const iAssess = findHeading(lower, [
    'full assessment',
    'contract security assessment',
    'security assessment',
  ]);
  const iChecklist = findHeading(lower, ['audit checklist', 'checklist']);

  if (iSummary < 0 && iAssess < 0 && iChecklist < 0) {
    // Nothing matched — expose the whole report under "summary" so the
    // user still has visibility; other tabs stay empty.
    return { summary: md, assessment: '', checklist: '' };
  }

  return {
    summary: pick(iSummary, iAssess >= 0 ? iAssess : iChecklist),
    assessment: pick(iAssess, iChecklist),
    checklist: pick(iChecklist, -1),
  };
}

function findHeading(lower, needles) {
  // Accept any heading depth (^#{1,6}\s*<needle>)
  for (const n of needles) {
    const re = new RegExp('(^|\\n)#{1,6}\\s*' + escapeRe(n), 'i');
    const m = re.exec(lower);
    if (m) {
      const idx = lower.indexOf(m[0], 0);
      // skip the leading newline if present so we return the line start
      return idx + (m[1] ? 1 : 0);
    }
  }
  return -1;
}
function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Trigger a client-side download of the given text blob. */
export function downloadBlob({ text, filename, mime = 'text/plain' }) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    a.remove();
    URL.revokeObjectURL(url);
  }, 200);
}

/**
 * Derive a coarse D/C/B/A/S letter rating from statistics.
 * Mirrors the skill's scoring intent without duplicating the exact
 * formula — fine for the report header badge.
 */
export function ratingFromStats(stats) {
  if (!stats) return 'U';
  const { critical = 0, high = 0, medium = 0, low = 0 } = stats;
  if (critical > 0) return 'D';
  if (high > 0) return 'C';
  if (medium > 2) return 'C';
  if (medium > 0) return 'B';
  if (low > 0) return 'A';
  return 'S';
}
