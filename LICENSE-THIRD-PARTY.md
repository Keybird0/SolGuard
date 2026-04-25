# Third-Party Licenses

SolGuard is licensed under the [MIT License](./LICENSE). It depends on
third-party software distributed under its own licenses. This file
enumerates the direct runtime / dev dependencies of SolGuard and their
licenses. It is **informational**; the authoritative source is each
package's own `LICENSE` file inside `node_modules/` or `site-packages/`.

Last updated: 2026-04-24 (Phase 5 · Lark notify port)

---

## Node.js dependencies (`solguard-server/`)

| Package | Version | License |
|---------|---------|---------|
| `@solana/pay` | ^0.2.6 | Apache-2.0 |
| `@solana/web3.js` | ^1.95.0 | Apache-2.0 |
| `bignumber.js` | ^9.1.2 | MIT |
| `cors` | ^2.8.5 | MIT |
| `dotenv` | ^16.4.5 | BSD-2-Clause |
| `express` | ^4.19.2 | MIT |
| `nodemailer` | ^6.9.14 | MIT |
| `pino` | ^9.3.2 | MIT |
| `pino-http` | ^10.2.0 | MIT |
| `uuid` | ^10.0.0 | MIT |
| `zod` | ^3.23.8 | MIT |

### Dev dependencies

| Package | License |
|---------|---------|
| `typescript` | Apache-2.0 |
| `tsx` | MIT |
| `eslint` | MIT |
| `prettier` | MIT |
| `@typescript-eslint/*` | MIT / BSD-2-Clause |

## Python dependencies (`skill/solana-security-audit-skill/`)

| Package | License |
|---------|---------|
| `anthropic` | MIT |
| `openai` | Apache-2.0 |
| `pydantic` | MIT |
| `python-dotenv` | BSD-3-Clause |
| `pyyaml` | MIT |
| `httpx` | BSD-3-Clause |
| `tenacity` | Apache-2.0 |
| `pytest` | MIT |
| `ruff` | MIT |
| `black` | MIT |
| `mypy` | MIT |

## Upstream projects used as references

These projects inform SolGuard's architecture, rule design and SOP text.
Source clones may be placed under `../` locally and are git-ignored.
Where SolGuard incorporates any text / decision tables / prompt templates
from an upstream project, the specific file and Attribution condition are
listed below.

- **OpenHarness** — Apache-2.0 (consult upstream). Used as Agent runtime;
  no files redistributed in this repository.
- **GoatGuard** — consult upstream. Used as architectural reference.
- **Contract_Security_Audit_Skill** — MIT (© 2026 Keybird). See
  Attribution table below — SolGuard's
  `skill/solana-security-audit-skill/SKILL.md` and
  `references/workflow.md` incorporate the Solana-applicable subset of
  the upstream SOP.
- **Sealevel Attacks** (coral-xyz) — consult upstream. Used as vulnerability
  knowledge reference for `references/vulnerability-patterns.md`.

### Attribution table (MIT NOTICE requirement)

| SolGuard file | Upstream source | Portion incorporated | Upstream licence |
|---|---|---|---|
| `skill/solana-security-audit-skill/SKILL.md` | `Contract_Security_Audit_Skill/skill/SKILL.md` + `references/audit-sop.md` | YAML description style; Solana Authority risk matrix (§1.2-SOL); Token-2022 extensions red-flag list; attacker 10-questions short form; D/C/B/A/S rating scale | MIT |
| `skill/solana-security-audit-skill/references/workflow.md` | `Contract_Security_Audit_Skill/skill/references/audit-sop.md` (§1.2-SOL, §1.6-SOL, §3 Solana sub-rows, §4.3.1–4.3.4, §6.5, §7.1–7.2) and `references/workflow.md` | Solana attacker-10-questions full table; sibling-function consistency audit procedure; 6-step attack-scenario modelling; 7-Question Gate; scoring formula structure; report section taxonomy | MIT |
| `skill/solana-security-audit-skill/references/vulnerability-patterns.md` | `Contract_Security_Audit_Skill/skill/references/bug-class-patterns.md` (§"通用根因模式 3 大隐含假设" · "Severity 降级触发器" · Quick Reference 表式) + `coral-xyz/sealevel-attacks` (#0, #1, #3, #5, #7, #9) | 3-类假设根因模型（A/B/C）重述为 Solana 语境；Severity 降级触发器表；Quick Reference 表格式；7 条 Solana 规则的 Bad/Good 对比受 Sealevel-Attacks 启发 | MIT (upstream) · Apache-2.0 (Sealevel-Attacks) |
| `skill/solana-security-audit-skill/references/report-templates.md` | `Contract_Security_Audit_Skill/skill/references/report-templates.md` (Template 1 Risk-Summary 头部、Template 2 14-节骨架、Template 3 Checklist 分类法、Section Data Sources 表、通用规则) | 3-级报告骨架（Risk Summary / Assessment / Checklist）；14 节编号；Section Data Sources 表；"禁止下一步/Next Steps"规则 | MIT |
| `skill/solana-security-audit-skill/references/best-practices.md` | `Contract_Security_Audit_Skill/skill/references/audit-sop.md` §"安全编码规范" + Anchor Book Security chapter + Neodyme Workshop | 分组体例（身份/生命周期/算术/资金/依赖）；BP 编号与规则回链格式 | MIT (upstream) |
| `skill/solana-security-audit-skill/tools/semgrep_runner.py` | `Contract_Security_Audit_Skill/skill/scripts/semgrep_runner.py` | Structural layout (CLI wrapper + graceful-degrade pattern); rewritten to drop upstream's `rpc_common` dependency and to return raw Semgrep JSON (AI-first evidence, no verdict reshaping) | MIT |
| `skill/solana-security-audit-skill/assets/semgrep-rules/` (4 × `solana-*.yaml`) | Inspired by `Contract_Security_Audit_Skill/skill/assets/semgrep-rules/` + Coral-xyz Sealevel-Attacks snippets | Solana-specific AST patterns: `AccountInfo`/`UncheckedAccount` field detection, unchecked `program_id` CPI, raw arithmetic on `.balance`/`.amount`, manual `AnchorDeserialize`/`try_from_slice` | MIT / Apache-2.0 (upstream) |
| `solguard-server/public/styles.css` + `public/app.js` (toast/spinner helpers) | `GoatGuard/agent-server/public/index.html` (CSS variable design-token system, `.card`/`.btn-primary`/`.btn-outline`/`.status-badge`/`.progress-bar .fill`/`.findings-grid` 5-column severity tiles/`.toast`/`.spinner`/`fadeUp` keyframe) | Component pattern library (CSS tokens + class names + layout grid); all copy/colors/logic rewritten for SolGuard's Solana purple/green palette and Solana Pay (not x402) flow | MIT (upstream © 2026 Keybird0) |
| `solguard-server/src/notify/lark.ts` | `GoatGuard/agent-server/feishu-integration.ts` (`sendWebhookRichAlert`, `notifyScanStarted`, `notifyScanCompleted`) | Incoming-webhook card shape (`msg_type: 'interactive'` + `card.header.template` + `elements[{ tag:'markdown' }]`); severity-coloured header template selection (crit→red / high→orange / else→green); fire-and-forget + warn-on-failure degradation pattern. Dropped upstream's bitable / docx_builtin_import / im_v1 branches — SolGuard only uses Lark for operator-side three-stage lifecycle cards (submitted / paid / completed-or-failed). Markdown body copy + task-shape mapping rewritten for SolGuard's `AuditTask` schema. | MIT (upstream © 2026 Keybird0) |
| `test-fixtures/real-world/small/rw01_signer_auth.rs` · `…/rw02_account_data_matching.rs` · `…/rw03_*…rw06_*` | Adapted from `coral-xyz/sealevel-attacks@24555d0` (programs/0-signer-authorization, 1-account-data-matching, 3-type-cosplay, 5-arbitrary-cpi, 7-bump-seed-canonicalization, 9-closing-accounts) | Vulnerability patterns (single-file, simplified); field names, module layout, and comments rewritten; each file carries an `SPDX-License-Identifier: MIT` header + `// Source:` attribution comment | Apache-2.0 (upstream; used as public educational corpus) |
| `test-fixtures/real-world/medium/*.rs` | Inspired by Anchor examples (`coral-xyz/anchor/tests/*`) + Solana program library snippets | Clean / vulnerable Anchor idioms for the medium-size benchmark tier (300–1000 LOC); reassembled from multiple upstream modules, field names and entry-point arrangements rewritten | Apache-2.0 / MIT (upstream) |
| `test-fixtures/real-world/large/rw11_amm_slice.rs` · `rw12_staking_slice.rs` | Curated slices of real-world Solana programs (AMM / staking patterns found in Jupiter, Marinade, Metaplex reference codebases) | Method signatures, account struct shapes, and key arithmetic paths; adapted to reproduce the specific bug classes SolGuard benchmarks (integer overflow, missing signer check, arbitrary CPI, missing owner check); upstream project ids + commit refs live inside each file's SPDX header | Apache-2.0 / MIT (per upstream; each file individually attributed) |

All incorporated portions were rewritten to:

1. remove EVM / Sui / Move-specific steps (chain-agnostic upstream text
   reduced to Solana-only),
2. replace generic tool names with SolGuard's `solana_*` tool interface,
3. map section IDs onto SolGuard's 7-step SOP (see workflow.md §"上游映射" table).

Upstream MIT licence text is reproduced below as required:

```
MIT License

Copyright (c) 2026 Keybird

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## License compatibility

All bundled dependencies use permissive licenses (MIT / BSD / Apache-2.0).
These are compatible with SolGuard's MIT license for both source and
binary redistribution. Apache-2.0 dependencies (`@solana/web3.js`,
`typescript`, `tenacity`, `openai`, `anchor`) carry a patent grant;
SolGuard inherits that grant when distributed together.

If you believe a package's license is misidentified here, please open an
issue at <https://github.com/Keybird0/SolGuard/issues>.
