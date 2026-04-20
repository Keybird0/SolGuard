# Changelog

All notable changes to SolGuard will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `NOTICE` and `LICENSE-THIRD-PARTY.md` — formal MIT + upstream licence attribution.
- SPDX identifier (`SPDX-License-Identifier: MIT`) block in both READMEs.

### Changed
- README License section expanded with explicit usage terms and pointers
  to NOTICE / LICENSE-THIRD-PARTY.

### Already in place
- `LICENSE` — full MIT text (© 2026 SolGuard Contributors).
- `solguard-server/package.json` — `"license": "MIT"`.
- `skill/solana-security-audit-skill/pyproject.toml` — `license = { text = "MIT" }`.
- MIT shields badge in README.

---
- Initial project scaffold (Phase 1)
- Repository layout: `solguard-server/`, `skill/`, `test-fixtures/`, `scripts/`, `docs/`
- Root config: `.gitignore`, `.env.example`, `.editorconfig`, `LICENSE` (MIT)
- Bilingual README (EN + zh-CN)
- Express + TypeScript backend scaffold with health check, task store, Zod validation
- OpenHarness Skill scaffold with 7-step audit SOP (`SKILL.md`)
- Python skill types, base rule registry, and placeholder modules for parse/scan/ai/report
- 5 seed test-fixture contracts (1 clean + 4 vulnerable)
- Vulnerability patterns + report templates + best practices references
- Phase 1 verification script (`scripts/verify-phase1.sh`)
- One-shot setup script (`scripts/setup.sh`)

[Unreleased]: https://github.com/Keybird0/SolGuard/compare/HEAD...HEAD
