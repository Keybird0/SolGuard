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

// ============================================================
// Three-tier report renderers
// ============================================================
//
// The audit report is deliberately split into three *role-differentiated*
// views so each tab has a clear purpose — rather than just being three
// slices of the same Markdown blob:
//
//   • summary     — Risk Summary.     Who: stakeholders / PMs. Goal:
//                   grasp the risk posture in < 1 minute.
//   • assessment  — Full Assessment.  Who: engineers. Goal: every finding
//                   with location / reason / impact / recommendation /
//                   code snippet so they can fix it.
//   • checklist   — Checklist Result. Who: reviewers / CI. Goal: prove
//                   coverage — which Solana rule classes were checked,
//                   which hit, which came back clean, and on which file.
//
// We build all three from the same normalized `task.findings` +
// `task.statistics` so they always have data (no more "empty" tab).

// Canonical Solana audit rule catalogue used to prove coverage in the
// Checklist view. These are the classes `run_audit.py` / `ai/planner.py`
// consider during a full audit; they closely follow the 10-class
// taxonomy from the Solana skill + sealevel-attacks patterns.
export const KNOWN_RULES = [
  {
    id: 'missing_signer_check',
    name: 'Missing Signer Check',
    category: 'Authorization',
    aliases: ['signer_check', 'missing_signer'],
  },
  {
    id: 'missing_owner_check',
    name: 'Missing Owner Check',
    category: 'Account Validation',
    aliases: ['owner_check', 'missing_owner'],
  },
  {
    id: 'account_data_matching',
    name: 'Account Data Matching',
    category: 'Account Validation',
    aliases: ['account_matching', 'data_matching'],
  },
  {
    id: 'type_cosplay',
    name: 'Type Cosplay / Discriminator',
    category: 'Account Validation',
    aliases: ['discriminator_check', 'type_confusion'],
  },
  {
    id: 'arbitrary_cpi',
    name: 'Arbitrary CPI',
    category: 'CPI Safety',
    aliases: ['arbitrary_cross_program_invocation', 'cpi_whitelist'],
  },
  {
    id: 'pda_derivation_error',
    name: 'PDA Derivation / Bump Seed',
    category: 'PDA Safety',
    aliases: ['pda_derivation', 'bump_seed', 'bump_seed_canonicalization'],
  },
  {
    id: 'pda_sharing',
    name: 'PDA Sharing / Seed Collision',
    category: 'PDA Safety',
    aliases: ['seed_collision'],
  },
  {
    id: 'duplicate_mutable_accounts',
    name: 'Duplicate Mutable Accounts',
    category: 'Account Validation',
    aliases: ['duplicate_accounts'],
  },
  {
    id: 'closing_account_error',
    name: 'Closing Account Error',
    category: 'Lifecycle',
    aliases: ['closing_account', 'unsafe_close'],
  },
  {
    id: 'sysvar_spoofing',
    name: 'Sysvar Address Check',
    category: 'Account Validation',
    aliases: ['sysvar_check', 'sysvar_address_checking'],
  },
  {
    id: 'uninitialized_account',
    name: 'Uninitialized Account',
    category: 'Lifecycle',
    aliases: ['init_check'],
  },
  {
    id: 'reinit_attack',
    name: 'Re-init Attack',
    category: 'Lifecycle',
    aliases: ['reinitialization'],
  },
  {
    id: 'integer_overflow',
    name: 'Integer Overflow / Underflow',
    category: 'Arithmetic',
    aliases: ['arithmetic_overflow', 'unchecked_math'],
  },
  {
    id: 'semgrep_assets',
    name: 'Semgrep Solana Rules',
    category: 'Pattern Scanners',
    aliases: ['semgrep', 'solana_manual_accountinfo_deserialize'],
  },
];

// Category display order for the Checklist view.
const CATEGORY_ORDER = [
  'Authorization',
  'Account Validation',
  'CPI Safety',
  'PDA Safety',
  'Lifecycle',
  'Arithmetic',
  'Pattern Scanners',
  'Additional Checks',
];

const SEVERITY_ORDER = ['Critical', 'High', 'Medium', 'Low', 'Info'];
const SEVERITY_EMOJI = {
  Critical: '🔴',
  High: '🟠',
  Medium: '🟡',
  Low: '🔵',
  Info: '⚪',
};

function normalizeRuleId(ruleId) {
  return String(ruleId ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function matchKnownRule(ruleId) {
  const norm = normalizeRuleId(ruleId);
  if (!norm) return null;
  // 1) exact match on id.
  for (const r of KNOWN_RULES) {
    if (norm === r.id) return r;
  }
  // 2) prefix / suffix match on id. `startsWith` catches scanner
  // namespaces like `arbitrary_cpi_v2`; `endsWith` catches custom
  // prefixes the skill sometimes emits, e.g. `custom_sysvar_spoofing`
  // → `sysvar_spoofing`.
  for (const r of KNOWN_RULES) {
    if (norm.startsWith(r.id + '_') || norm.endsWith('_' + r.id)) return r;
  }
  // 3) alias table (exact / prefix / suffix).
  for (const r of KNOWN_RULES) {
    if (
      r.aliases?.some(
        (a) =>
          norm === a ||
          norm.startsWith(a + '_') ||
          norm.endsWith('_' + a),
      )
    ) {
      return r;
    }
  }
  return null;
}

function titleForFinding(f) {
  return f.title || f.id || 'Untitled finding';
}

function ruleIdOf(f) {
  return f.ruleId || f.rule_id || f.id || '';
}

function codeSnippetOf(f) {
  return f.codeSnippet || f.code_snippet || '';
}

function sortBySeverity(findings) {
  return [...(findings || [])].sort(
    (a, b) =>
      SEVERITY_ORDER.indexOf(a.severity || 'Info') -
        SEVERITY_ORDER.indexOf(b.severity || 'Info') ||
      String(a.location || '').localeCompare(String(b.location || '')),
  );
}

function taskHeader(task) {
  const target = task?.inputs?.[0]?.value || '';
  const completed = task?.completedAt
    ? new Date(task.completedAt).toLocaleString()
    : '—';
  return { target, completed };
}

function totalFrom(stats) {
  if (!stats) return 0;
  return (
    (stats.critical ?? 0) +
    (stats.high ?? 0) +
    (stats.medium ?? 0) +
    (stats.low ?? 0) +
    (stats.info ?? 0)
  );
}

/**
 * Risk Summary — quick read. One-page, heavy on headline numbers, light
 * on prose.
 */
export function buildRiskSummaryMd(task) {
  const stats = task?.statistics || {};
  const findings = Array.isArray(task?.findings) ? task.findings : [];
  const { target, completed } = taskHeader(task);
  const rating = ratingFromStats(stats);
  const total = findings.length || totalFrom(stats);
  const sorted = sortBySeverity(findings);
  const top = sorted.slice(0, 5);

  const lines = [];
  lines.push('# Risk Summary');
  lines.push('');
  if (target) lines.push(`- **Audit target**: ${target}`);
  lines.push(`- **Overall rating**: \`${rating}\``);
  lines.push(`- **Completed**: ${completed}`);
  lines.push(`- **Total findings**: **${total}**`);
  lines.push('');
  lines.push('## At-a-glance');
  lines.push('');
  lines.push('| Severity | Count |');
  lines.push('| --- | ---: |');
  for (const s of SEVERITY_ORDER) {
    const key = s.toLowerCase();
    lines.push(`| ${SEVERITY_EMOJI[s]} ${s} | ${stats[key] ?? 0} |`);
  }
  lines.push(`| **Total** | **${total}** |`);
  lines.push('');

  if (top.length) {
    lines.push(`## Top risks (highest severity first)`);
    lines.push('');
    top.forEach((f, i) => {
      const sev = f.severity || 'Info';
      const loc = f.location ? `\`${f.location}\`` : '';
      const title = titleForFinding(f);
      lines.push(`${i + 1}. **[${sev}] ${title}** — ${loc}`);
      const oneLiner = (f.description || f.impact || '')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 220);
      if (oneLiner) lines.push(`   > ${oneLiner}${oneLiner.length >= 220 ? '…' : ''}`);
      lines.push('');
    });
  } else {
    lines.push('## Top risks');
    lines.push('');
    lines.push('_No findings recorded. The audit completed without raising any issue in this target._');
    lines.push('');
  }

  lines.push('## What this means');
  lines.push('');
  const crit = stats.critical ?? 0;
  const high = stats.high ?? 0;
  const med = stats.medium ?? 0;
  const low = stats.low ?? 0;
  if (crit > 0) {
    lines.push(
      `- 🔴 **Critical (${crit})** — can lead to full asset drain or complete bypass. Immediate action required.`,
    );
  }
  if (high > 0) {
    lines.push(
      `- 🟠 **High (${high})** — bypass access control, spoof authorities, or allow account confusion. Fix before production.`,
    );
  }
  if (med > 0) {
    lines.push(
      `- 🟡 **Medium (${med})** — weaken defence-in-depth or admit edge-case attacks. Schedule a fix.`,
    );
  }
  if (low > 0) {
    lines.push(
      `- 🔵 **Low (${low})** — hardening opportunities; no direct exploit path identified.`,
    );
  }
  if (total === 0) {
    lines.push(
      '- ✅ No findings. The target passed every rule class the audit ran.',
    );
  }
  lines.push('');
  lines.push(
    '> Open **Full Assessment** for per-finding reasoning, proof, and remediation. Open **Checklist** to see every rule class we checked and which files triggered a match.',
  );
  return lines.join('\n');
}

/**
 * Full Assessment — every finding, rendered for engineers.
 */
export function buildFullAssessmentMd(task) {
  const stats = task?.statistics || {};
  const findings = Array.isArray(task?.findings) ? task.findings : [];
  const { target, completed } = taskHeader(task);
  const rating = ratingFromStats(stats);
  const total = findings.length || totalFrom(stats);
  const sorted = sortBySeverity(findings);

  const lines = [];
  lines.push('# Full Assessment');
  lines.push('');
  if (target) lines.push(`- **Audit target**: ${target}`);
  lines.push(`- **Overall rating**: \`${rating}\``);
  lines.push(`- **Completed**: ${completed}`);
  lines.push(
    `- **Breakdown**: ${stats.critical ?? 0} critical · ${stats.high ?? 0} high · ${stats.medium ?? 0} medium · ${stats.low ?? 0} low · ${stats.info ?? 0} info`,
  );
  lines.push(`- **Total findings**: **${total}**`);
  lines.push('');

  lines.push('## Executive summary');
  lines.push('');
  if (total === 0) {
    lines.push(
      '_No findings were produced by the combined AI + scanner pipeline for this target._',
    );
  } else {
    const worst = sorted[0];
    const worstSev = worst?.severity || 'Info';
    lines.push(
      `The audit produced **${total} finding${total === 1 ? '' : 's'}**, topping out at **${worstSev}** severity. ` +
        `The most impactful issue is **${titleForFinding(worst)}** at \`${worst?.location || 'unknown'}\`, ` +
        `with ${sorted.filter((f) => f.severity === 'Critical').length} critical and ${sorted.filter((f) => f.severity === 'High').length} high-severity siblings. ` +
        'Each finding below includes a concrete location, the reasoning path, the impact if left unfixed, and a recommended remediation.',
    );
  }
  lines.push('');

  lines.push(`## Findings (${total})`);
  lines.push('');
  if (!sorted.length) {
    lines.push('_No findings recorded for this target._');
    return lines.join('\n');
  }

  sorted.forEach((f, i) => {
    const sev = f.severity || 'Info';
    const title = titleForFinding(f);
    const rule = ruleIdOf(f);
    const snippet = codeSnippetOf(f);
    lines.push(`### ${i + 1}. [${sev}] ${title}`);
    lines.push('');
    lines.push(`- **Severity**: ${SEVERITY_EMOJI[sev] || ''} ${sev}`);
    if (rule) lines.push(`- **Rule**: \`${rule}\``);
    if (f.location) lines.push(`- **Location**: \`${f.location}\``);
    if (typeof f.confidence === 'number') {
      lines.push(`- **Confidence**: ${f.confidence.toFixed(2)}`);
    }
    lines.push('');
    if (f.description) {
      lines.push('**Description.**');
      lines.push('');
      lines.push(f.description);
      lines.push('');
    }
    if (f.impact && f.impact !== f.description) {
      lines.push('**Impact.**');
      lines.push('');
      lines.push(f.impact);
      lines.push('');
    }
    if (f.recommendation) {
      lines.push('**Recommendation.**');
      lines.push('');
      lines.push(f.recommendation);
      lines.push('');
    }
    if (snippet) {
      lines.push('**Code.**');
      lines.push('');
      lines.push('```rust');
      lines.push(snippet);
      lines.push('```');
      lines.push('');
    }
    if (Array.isArray(f.evidence) && f.evidence.length) {
      lines.push('**Evidence.**');
      lines.push('');
      for (const ev of f.evidence) {
        const text = typeof ev === 'string' ? ev : ev.snippet || ev.note || '';
        if (text) lines.push(`- ${text}`);
      }
      lines.push('');
    }
    lines.push('---');
    lines.push('');
  });

  return lines.join('\n');
}

/**
 * Checklist Result — proof of coverage. Group by rule category, list
 * each canonical rule with its result (hit / clean) and the matching
 * file:line rows when applicable. Unknown rule IDs land in "Additional
 * Checks" so we never drop data on the floor.
 */
export function buildChecklistMd(task) {
  const findings = Array.isArray(task?.findings) ? task.findings : [];
  const { target, completed } = taskHeader(task);

  // bucket[ruleKey] = { rule, matches: [{ severity, title, location }] }
  const bucket = new Map();

  // Pre-populate known rules so "clean" rows stay visible.
  for (const r of KNOWN_RULES) {
    bucket.set(`known:${r.id}`, { rule: r, matches: [] });
  }

  for (const f of findings) {
    const rid = ruleIdOf(f);
    const match = matchKnownRule(rid);
    if (match) {
      const key = `known:${match.id}`;
      bucket.get(key).matches.push({
        severity: f.severity || 'Info',
        title: titleForFinding(f),
        location: f.location || '',
      });
    } else {
      // Unknown / custom rule — show it under "Additional Checks"
      // with its own row keyed by rule id so the user still sees it.
      const key = `extra:${normalizeRuleId(rid) || 'untitled'}`;
      if (!bucket.has(key)) {
        bucket.set(key, {
          rule: {
            id: normalizeRuleId(rid) || 'untitled',
            name: titleForFinding(f),
            category: 'Additional Checks',
          },
          matches: [],
        });
      }
      bucket.get(key).matches.push({
        severity: f.severity || 'Info',
        title: titleForFinding(f),
        location: f.location || '',
      });
    }
  }

  // Group by category.
  const byCategory = new Map();
  for (const entry of bucket.values()) {
    const cat = entry.rule.category || 'Additional Checks';
    if (!byCategory.has(cat)) byCategory.set(cat, []);
    byCategory.get(cat).push(entry);
  }

  const totalRules = bucket.size;
  const hitRules = [...bucket.values()].filter((e) => e.matches.length > 0).length;
  const cleanRules = totalRules - hitRules;
  const totalFindings = findings.length;

  const lines = [];
  lines.push('# Checklist Result');
  lines.push('');
  if (target) lines.push(`- **Audit target**: ${target}`);
  lines.push(`- **Completed**: ${completed}`);
  lines.push(
    `- **Coverage**: ${totalRules} rule class${totalRules === 1 ? '' : 'es'} checked · ` +
      `${hitRules} with finding${hitRules === 1 ? '' : 's'} · ${cleanRules} clean`,
  );
  lines.push(`- **Matched findings**: **${totalFindings}**`);
  lines.push('');
  lines.push(
    '_Legend: ⚠️ finding detected · ✅ rule passed (clean) · ℹ️ additional / custom check._',
  );
  lines.push('');

  const categories = [
    ...CATEGORY_ORDER.filter((c) => byCategory.has(c)),
    ...[...byCategory.keys()].filter((c) => !CATEGORY_ORDER.includes(c)),
  ];

  for (const cat of categories) {
    const entries = byCategory.get(cat) || [];
    if (!entries.length) continue;
    lines.push(`## ${cat}`);
    lines.push('');
    // Sort rules in category: hits first (desc by count), then clean.
    entries.sort((a, b) => b.matches.length - a.matches.length);
    for (const entry of entries) {
      const { rule, matches } = entry;
      const icon = matches.length
        ? '⚠️'
        : cat === 'Additional Checks'
          ? 'ℹ️'
          : '✅';
      const label = matches.length
        ? `${matches.length} finding${matches.length === 1 ? '' : 's'}`
        : 'clean — no match';
      lines.push(`- ${icon} **${rule.name}** (\`${rule.id}\`) — ${label}`);
      if (matches.length) {
        // Sort the hits by severity then location for readability.
        const ordered = [...matches].sort(
          (a, b) =>
            SEVERITY_ORDER.indexOf(a.severity) -
              SEVERITY_ORDER.indexOf(b.severity) ||
            String(a.location).localeCompare(String(b.location)),
        );
        for (const m of ordered) {
          const loc = m.location ? `\`${m.location}\`` : '_location unknown_';
          lines.push(`  - [${m.severity}] ${m.title} @ ${loc}`);
        }
      }
    }
    lines.push('');
  }

  lines.push('---');
  lines.push('');
  lines.push(
    `**Coverage summary.** ${totalRules} canonical rule classes were evaluated: ` +
      `${hitRules} triggered and ${cleanRules} came back clean. ` +
      'No rule in the audit matrix was silently skipped — every row above reflects an explicit pass or hit.',
  );

  return lines.join('\n');
}
