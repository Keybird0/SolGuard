<div align="center">

# SolGuard

**AI-powered security audit for Solana smart contracts.**
**Free · Open-source · Instant.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Made for Solana](https://img.shields.io/badge/Made%20for-Solana-14F195)](https://solana.com)
[![Status: WIP](https://img.shields.io/badge/Status-WIP-orange)](#roadmap)

**[简体中文](./README.zh-CN.md)** · [Live Demo (WIP)](#) · [Video (WIP)](#) · [Docs](./docs/)

</div>

---

## Why SolGuard?

Professional Solana security audits cost **$50,000+** and take **2–4 weeks**.
**90%+ of small-to-medium projects** can't afford them — yet ship code that holds real user funds.

**SolGuard is a free, open-source AI security auditor** that turns any GitHub URL / contract address / whitepaper into a professional-grade risk report in **under 5 minutes** for **0.01 SOL** (roughly $2).

| | Pro Audit | SolGuard |
|---|---|---|
| Cost | $50,000+ | 0.01 SOL (~$2) |
| Turnaround | 2–4 weeks | < 5 min |
| Coverage | Deep, human | 7+ rules + AI reasoning |
| Availability | Booking required | 24/7 self-serve |

---

## Features

- **4 input types** — GitHub repo · on-chain program address · whitepaper URL · project website
- **7+ Solana-specific rules** — Missing Signer/Owner Check · Arbitrary CPI · Integer Overflow · Account Data Matching · PDA Derivation Error · Uninitialized Account
- **AI deep analysis + Kill Signal** — LLM-powered reasoning cross-checks findings to cut false positives
- **3-tier report** — Risk Summary (executive) · Contract Assessment (technical) · Audit Checklist (actionable)
- **Solana Pay checkout** — native in-wallet payment in < 10 seconds
- **Email delivery + feedback loop** — reports sent to your inbox; feedback closes the loop

---

## Architecture

```
┌───────────────────────────────────────────────────────┐
│              Web UI (HTML + Tailwind CDN)             │
│  submit · pay · progress · report · feedback          │
└──────────────────────┬────────────────────────────────┘
                       │ REST
┌──────────────────────┴────────────────────────────────┐
│      Express Server (TypeScript, Node ≥ 20)          │
│  routes · task store · payment · email · agent-client │
└──────────────────────┬────────────────────────────────┘
                       │ spawn / CLI
┌──────────────────────┴────────────────────────────────┐
│           OpenHarness Agent (Python ≥ 3.10)          │
│     Skill: solana-security-audit-skill                │
│    tools: parse · scan · ai · report                  │
└───────────────────────────────────────────────────────┘
```

Full architecture doc (coming soon): [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)

---

## Repository Layout

```
SolGuard/
├── solguard-server/                # Express + TS backend
│   ├── src/                        # server.ts · routes · middleware · storage
│   ├── public/                     # single-page Web UI
│   └── tests/
├── skill/
│   └── solana-security-audit-skill/
│       ├── SKILL.md                # Skill definition + audit SOP
│       ├── tools/                  # solana_parse · solana_scan · solana_report
│       │   └── rules/              # 7 security rules
│       ├── ai/                     # LLM analyzer + prompts
│       ├── core/                   # types + utilities
│       ├── reporters/              # 3-tier report generators
│       ├── references/             # vulnerability patterns + templates
│       └── tests/
├── test-fixtures/
│   ├── contracts/                  # seed fixtures (Phase 1)
│   └── real-world/                 # benchmark fixtures (Phase 6)
├── scripts/                        # verify · setup · deploy
├── docs/                           # architecture · usage · demo · case studies
└── .env.example
```

---

## Quick Start

### Prerequisites

- **Node.js** ≥ 20
- **Python** ≥ 3.10
- **Solana CLI** (for Devnet testing)
- **OpenHarness** (`pip install openharness-ai`)
- Anthropic or OpenAI API key

### Setup

```bash
git clone https://github.com/Keybird0/SolGuard.git
cd SolGuard

# One-shot setup script (coming soon)
bash scripts/setup.sh

# Or manually:
cp .env.example .env                     # fill in secrets
cd solguard-server && npm install
cd ../skill/solana-security-audit-skill && pip install -r requirements.txt
```

### Run locally

```bash
cd solguard-server
npm run dev
# → open http://localhost:3000
```

### Verify Phase 1 setup

```bash
bash scripts/verify-phase1.sh
```

---

## Supported Vulnerabilities

| # | Rule | Severity | Status |
|---|------|----------|--------|
| 1 | Missing Signer Check | High | 🚧 WIP |
| 2 | Missing Owner Check | High | 🚧 WIP |
| 3 | Integer Overflow | Medium | 🚧 WIP |
| 4 | Arbitrary CPI | Critical | 🚧 WIP |
| 5 | Account Data Matching | High | 🚧 WIP |
| 6 | PDA Derivation Error | High | 🚧 WIP |
| 7 | Uninitialized Account | Medium | 🚧 WIP |

Details: [`docs/knowledge/solana-vulnerabilities.md`](./docs/knowledge/solana-vulnerabilities.md) (coming soon)

---

## Roadmap

- **Phase 1** — Environment & scaffolding ✅
- **Phase 2** — Skill + 7 rules + AI analyzer
- **Phase 3** — Express server + payment + email
- **Phase 4** — Web UI
- **Phase 5** — Integration + deployment
- **Phase 6** — Benchmark + accuracy tuning
- **Phase 7** — Docs + demo + submission (May 11, 2026)

See full plan in [`docs/04-SolGuard项目管理/`](../docs/04-SolGuard%E9%A1%B9%E7%9B%AE%E7%AE%A1%E7%90%86/).

---

## Contributing

Contributions welcome! See [`CONTRIBUTING.md`](./CONTRIBUTING.md) (coming soon).

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

You are free to use, modify, and distribute this software — commercially
or otherwise — provided you preserve the above copyright notice and the
MIT license text in all copies or substantial portions of the Software.

---

## Credits

SolGuard stands on the shoulders of giants:

- **[OpenHarness](https://github.com/HKUDS/OpenHarness)** — Agent infrastructure
- **[GoatGuard](https://github.com/Reappear/GoatGuard)** — EVM audit architecture reference
- **[Sealevel Attacks](https://github.com/coral-xyz/sealevel-attacks)** — Security benchmark
- **Solana Foundation** — Docs & community
