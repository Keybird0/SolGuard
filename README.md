<div align="center">

# SolGuard

**AI-powered security audit for Solana smart contracts.**
**Affordable · Open-source · Instant.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Made for Solana](https://img.shields.io/badge/Made%20for-Solana-14F195)](https://solana.com)
[![Live Demo](https://img.shields.io/badge/Live_Demo-solguard--demo.vercel.app-00c853)](https://solguard-demo.vercel.app/)
[![Phase](https://img.shields.io/badge/Phase-7%20Docs%20%26%20Demo-blue)](./docs/04-SolGuard%E9%A1%B9%E7%9B%AE%E7%AE%A1%E7%90%86/)

**[简体中文](./README.zh-CN.md)** · [**Live Demo**](https://solguard-demo.vercel.app/) · [Case Studies](./docs/case-studies/) · [Docs](./docs/)

</div>

---

## Why SolGuard?

Professional Solana security audits cost **$50,000+** and take **2–4 weeks**.
**90%+ of small-to-medium projects** can't afford them — yet ship code that holds real user funds.

**SolGuard is a low-cost, open-source AI security auditor** that turns any GitHub URL / on-chain program address / whitepaper into a professional-grade risk report in **under 5 minutes** for **0.01 SOL per target** (roughly $2).

| | Pro Audit | SolGuard |
|---|---|---|
| Cost | $50,000+ | 0.01 SOL (~$2) per target |
| Turnaround | 2–4 weeks | < 5 min |
| Coverage | Deep, human | 7 deterministic rules + AI cross-validation |
| Availability | Booking required | 24/7 self-serve |

---

## Try it in 30 seconds

Click **[solguard-demo.vercel.app](https://solguard-demo.vercel.app/)** — a fully-playable demo runs entirely in your browser (mock wallet, 3 pre-generated case reports). No SOL needed, no Phantom install, no keys. You can submit any input, walk through the full Submit → Pay → Progress → Report flow, and inspect the three-tier audit output for each of the bundled cases.

| Case | Contract | Findings | Mode |
|---|---|---|---|
| [01 · Arbitrary CPI](./docs/case-studies/01-multi-vuln-cpi/) | 51-line Anchor (Sealevel §5) | **1 Critical** | Demo-canned |
| [02 · Clean Escrow](./docs/case-studies/02-clean-escrow/) | 172-line Anchor | 0 | Demo-canned |
| [03 · Staking Slice](./docs/case-studies/03-staking-slice/) | 312-line Anchor + legacy path | 2 High · 1 Medium | Demo-canned |

> **Demo Mode caveat** — the hosted demo replays frozen reports. To run a real end-to-end scan against your own contract, self-host the stack (see [Quick Start](#quick-start)). The demo is feature-complete for UI exploration but does *not* call the LLM or execute the audit pipeline.

---

## Features

- **4 input types** — GitHub repo · on-chain program address · whitepaper URL · project website
- **7 Solana-specific rules** — Missing Signer Check · Missing Owner Check · Arbitrary CPI · Integer Overflow · Account Data Matching · PDA Derivation Error · Uninitialized Account
- **AI deep analysis + Kill Signal** — LLM-powered reasoning cross-validates rule hits to cut false positives (Phase 6 precision on Sealevel-benchmark: 88%, recall: 79%)
- **3-tier report** — Risk Summary (executive) · Contract Assessment (technical) · Audit Checklist (actionable)
- **Solana Pay checkout** — native in-wallet payment in < 10 seconds, Devnet or Mainnet
- **Email delivery + feedback loop** — reports sent to your inbox; signed feedback closes the loop
- **Batch submissions** — audit up to 3 targets in one atomic payment
- **Swagger / OpenAPI 3** — machine-readable API spec at [`solguard-server/openapi.yaml`](./solguard-server/openapi.yaml)

---

## Architecture

```mermaid
flowchart LR
    U[User Browser] -->|REST / Solana Pay| W[Web UI · public/]
    W -->|fetch /api/*| S[Express Server<br/>Node ≥ 20]
    S -->|spawn / CLI| A[OpenHarness Agent<br/>Python ≥ 3.11]
    A -->|Skill: solana-security-audit-skill| T[7 rules + AI analyzer]
    T -->|3-tier report| S
    S -->|SMTP| E[(Email)]
    S -->|Solana Pay poller| C[(Solana Devnet<br/>Mainnet)]

    subgraph Vercel Demo Mode
      direction LR
      W2[Web UI · same files] -->|demo-shim.js intercepts| M[(Pre-generated<br/>/demo-data/*)]
    end
```

Full architecture + ADRs: [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).

---

## Repository Layout

```
SolGuard/
├── solguard-server/                # Express + TS backend + static UI
│   ├── src/                        # server.ts · routes · audit-engine · payment · email
│   ├── public/                     # single-page Web UI (also deployed to Vercel as demo)
│   ├── tests/
│   └── openapi.yaml                # OpenAPI 3 spec
├── skill/
│   └── solana-security-audit-skill/
│       ├── SKILL.md                # Skill definition + audit SOP
│       ├── tools/                  # solana_parse · solana_scan · solana_ai_analyze · solana_report
│       │   └── rules/              # 7 security rules
│       ├── ai/                     # LLM analyzer + prompts
│       ├── core/                   # types + utilities
│       ├── reporters/              # 3-tier report generators
│       ├── references/             # vulnerability patterns + templates
│       └── tests/
├── test-fixtures/                  # seed + real-world benchmark contracts
├── scripts/                        # verify · setup · deploy · benchmark
├── docs/
│   ├── ARCHITECTURE.md             # system diagram + ADRs
│   ├── USAGE.md / USAGE.zh-CN.md   # end-user guide + FAQ
│   ├── case-studies/               # 3 pre-generated audit reports
│   ├── demo/                       # demo script + slidev deck
│   └── knowledge/                  # vulnerability knowledge base
├── outputs/                        # benchmark + phase-baseline reports
└── .env.example
```

---

## Quick Start

### Prerequisites

- **Node.js** ≥ 20
- **[uv](https://docs.astral.sh/uv/)** ≥ 0.4 — **the only supported Python toolchain for SolGuard**
  - uv manages the Python interpreter (3.11, pinned via `.python-version`), virtualenv, dependencies and `uv.lock`.
  - `pip` / `venv` / `poetry` / `conda` are **not** supported as the primary workflow.
- **Solana CLI** (for Devnet testing)
- **OpenHarness** — installed through uv: `uv tool install openharness-ai`
- Anthropic or OpenAI API key

> No uv yet?
>
> ```bash
> curl -LsSf https://astral.sh/uv/install.sh | sh   # or:  brew install uv
> ```

### Setup

```bash
git clone https://github.com/Keybird0/SolGuard.git
cd SolGuard

# One-shot setup (auto-checks uv, runs `npm install` + `uv sync`,
# then executes the Phase 1 verification script)
bash scripts/setup.sh

# Or manually:
cp .env.example .env                              # fill in secrets
cd solguard-server && npm install && cd ..
cd skill/solana-security-audit-skill
uv sync --extra test                              # creates .venv + installs deps from uv.lock
```

### Run locally

```bash
# Backend
cd solguard-server && npm run dev
# → open http://localhost:3000

# Skill commands — always via `uv run` (no `activate` needed)
cd skill/solana-security-audit-skill
uv run pytest -q
uv run ruff check .
```

### Verify Phase 1 setup

```bash
bash scripts/verify-phase1.sh
```

### Dependency management cheatsheet (Python)

```bash
cd skill/solana-security-audit-skill

uv sync                   # install runtime + dev deps (reads pyproject.toml + uv.lock)
uv sync --extra test      # + pytest stack
uv sync --extra parser    # + tree-sitter-rust (Phase 6 optional parser)
uv add pydantic-settings  # add a runtime dep (updates pyproject.toml + uv.lock)
uv add --dev pytest-mock  # add a dev-only dep
uv remove tenacity        # remove a dep
uv lock                   # refresh the lockfile without syncing
uv lock --check           # CI guard: fail if lock and pyproject drift
uv run <any-command>      # run inside the managed venv

# Generate pip-compatible requirements (for platforms that only speak pip)
uv export --format requirements-txt --no-hashes --no-dev > requirements.txt
```

> `uv.lock` is the source of truth — **commit it** with every dependency change.

Full guide: [`docs/USAGE.md`](./docs/USAGE.md) (English) / [`docs/USAGE.zh-CN.md`](./docs/USAGE.zh-CN.md) (中文).

---

## Supported Vulnerabilities

Rules are implemented in [`skill/solana-security-audit-skill/tools/rules/`](./skill/solana-security-audit-skill/tools/rules/) and validated against the Sealevel-Attacks corpus + 16 real-world fixtures.

| # | Rule | Severity | Status |
|---|------|----------|--------|
| 1 | Missing Signer Check | High | ✅ |
| 2 | Missing Owner Check | High | ✅ |
| 3 | Integer Overflow | Medium | ✅ |
| 4 | Arbitrary CPI | Critical | ✅ |
| 5 | Account Data Matching | High | ✅ |
| 6 | PDA Derivation Error | High | ✅ |
| 7 | Uninitialized Account | Medium | ✅ |

Deep-dive per rule (definition · bad/good code · detection notes · external refs): [`docs/knowledge/solana-vulnerabilities.md`](./docs/knowledge/solana-vulnerabilities.md).

---

## API

SolGuard exposes an OpenAPI 3 REST API. Spec: [`solguard-server/openapi.yaml`](./solguard-server/openapi.yaml). When the server is running locally, Swagger UI is served at `http://localhost:3000/docs`.

Key endpoints:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/audit` | Submit a batch of up to 3 targets |
| `GET` | `/api/audit/batch/:batchId` | Poll batch status + per-task progress |
| `POST` | `/api/audit/batch/:batchId/payment` | Submit a Solana Pay signature for verification |
| `GET` | `/api/audit/:taskId/report.md` | Fetch the 3-tier Markdown report |
| `GET` | `/api/audit/:taskId/report.json` | Machine-readable findings + stats |
| `POST` | `/api/feedback` | Submit a signed Ed25519 feedback message |
| `GET` | `/healthz` | Liveness / readiness probe |

---

## Roadmap

- **Phase 1** — Environment & scaffolding ✅
- **Phase 2** — Skill + 7 rules + AI analyzer ✅
- **Phase 3** — Express server + payment + email ✅
- **Phase 4** — Web UI ✅
- **Phase 5** — Integration + deployment ✅
- **Phase 6** — Benchmark + accuracy tuning ✅
- **Phase 7** — Docs + demo + submission (May 11, 2026) 🚧

See full plan in [`docs/04-SolGuard项目管理/`](../docs/04-SolGuard%E9%A1%B9%E7%9B%AE%E7%AE%A1%E7%90%86/).

---

## Contributing

Contributions welcome! See [`CONTRIBUTING.md`](./CONTRIBUTING.md).

Rough workflow:
1. Fork & clone
2. `bash scripts/setup.sh`
3. Create a feature branch
4. Commit via [Conventional Commits](https://www.conventionalcommits.org/)
5. Open a PR

---

## License

SolGuard is released under the **[MIT License](./LICENSE)** — see
[`LICENSE`](./LICENSE) for the full text.

```
SPDX-License-Identifier: MIT
Copyright (c) 2026 SolGuard Contributors
```

Third-party dependencies retain their original licenses; see
[`LICENSE-THIRD-PARTY.md`](./LICENSE-THIRD-PARTY.md) and
[`NOTICE`](./NOTICE).

---

## Credits

SolGuard stands on the shoulders of giants:

- **[OpenHarness](https://github.com/HKUDS/OpenHarness)** — Agent infrastructure
- **[GoatGuard](https://github.com/Reappear/GoatGuard)** — EVM audit architecture reference
- **[Sealevel Attacks](https://github.com/coral-xyz/sealevel-attacks)** — Security benchmark
- **Solana Foundation** — Docs & community
