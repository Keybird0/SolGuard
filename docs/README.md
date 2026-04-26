# SolGuard Internal Documentation

This folder holds the **in-repo** technical documentation shipped with
the SolGuard codebase. Higher-level hackathon planning lives one level
up, outside of this repo, at `../docs/04-SolGuard项目管理/` (relative
to the monorepo root — see that directory for the full project plan).

---

## Documentation status (Phase 7 complete)

| Document | Owner Phase | Status | Path |
|---|---|---|---|
| `ARCHITECTURE.md` (system diagram + ADRs 001–009) | Phase 7 §P7.1.2 | ✅ DONE (347 lines) | [`ARCHITECTURE.md`](./ARCHITECTURE.md) |
| `USAGE.md` / `USAGE.zh-CN.md` (end-user guide + FAQ) | Phase 7 §P7.1.3 | ✅ DONE (207 / 207 lines, bilingual) | [`USAGE.md`](./USAGE.md) · [`USAGE.zh-CN.md`](./USAGE.zh-CN.md) |
| API spec (machine-readable) | Phase 5 §P5.1.1 | ✅ DONE (OpenAPI 3) | [`solguard-server/openapi.yaml`](../solguard-server/openapi.yaml) — served as Swagger UI at `http://localhost:3000/docs` when the server is running. No standalone `API.md` is generated; the YAML is the source of truth. |
| `CONTRIBUTING.md` | Phase 7 §P7.2.2 | ✅ DONE (390 lines) | [`../CONTRIBUTING.md`](../CONTRIBUTING.md) |
| `knowledge/solana-vulnerabilities.md` (rule deep-dive) | Phase 7 §P7.2.3 | ✅ DONE (768 lines) | [`knowledge/solana-vulnerabilities.md`](./knowledge/solana-vulnerabilities.md) |
| `demo/script.md` (demo script + speaker notes) | Phase 7 §P7.3.1 | ✅ DONE | [`demo/script.md`](./demo/script.md) — also includes [`demo/deck-source.md`](./demo/deck-source.md) (slides) and [`demo/deck-notes.md`](./demo/deck-notes.md) (presenter notes) |
| `case-studies/` (3 benchmark-backed reports) | Phase 7 §P7.3.4 | ✅ DONE | [`case-studies/README.md`](./case-studies/README.md) — 3 cases (Arbitrary CPI / Clean Escrow / Staking Slice), each with `risk_summary.md` + `assessment.md` + `checklist.md` + `report.json` + `HIGHLIGHTS.md` |

---

## Existing subfolders

- [`assets/`](./assets/) — diagrams, logo, UI mockups (currently empty; populated as needed).
- [`demo/`](./demo/) — demo scripts (`script.md`), slide source (`deck-source.md`), presenter notes (`deck-notes.md`).
- [`case-studies/`](./case-studies/) — 3 benchmark-backed audit reports replayed by the Vercel Demo Mode.
- [`knowledge/`](./knowledge/) — public Solana vulnerability knowledge base (`solana-vulnerabilities.md`, 768 lines, per-rule deep-dive with bad/good code + external refs).

---

## Beyond Phase 7 (additions through v0.9, 2026-04-26)

- **A3 Deep-Dive Agent (v0.9 skill-first)** — `references/l3-agents-playbook.md` §3 adds a third L3 agent that runs after A1+A2 merge to catch sibling-drift / cross-cpi-taint / callee-arith / authority-drop blind spots. The playbook lives under `skill/.../references/` (gitignored per project convention; see `ARCHITECTURE.md` for design); SKILL.md and the top-level READMEs both list A3 in the Step 5.L3 stage table.
- **Gate1 / Gate4 fixes** — `ai/judge/kill_signal.py` no longer falls back to whole-file regex when scope is unresolvable (skip-match instead; trace records `signals_skipped_no_scope[]`); `ai/judge/seven_q_gate.py` Q3 returns provisional PASS for `rule_id=null` (A1 novel findings) instead of unilaterally KILLing them. See `CHANGELOG.md` "Unreleased" section for the commit hashes.
- **Claude Code dispatcher** — `scripts/skill_tool.py` (~165 lines) exposes all 9 thin tools through a single stdin/stdout JSON CLI so the SKILL can be loaded into Claude Code (in addition to OpenHarness). SKILL.md gains a "Claude Code Invocation Pattern" section documenting the symlink installation and the six-step Bash sequence.
- **Cashio infinite-mint PoC fixture** — `test-fixtures/known-incidents/cashio_poc.rs` reproduces the 2022-03 Cashio root cause (~$52M loss) in ~85 LOC. Verified end-to-end — SolGuard v0.9 catches the literal Critical / High root-cause findings.

For the underlying design rationale, see [`ARCHITECTURE.md`](./ARCHITECTURE.md) (ADRs 001–009).
