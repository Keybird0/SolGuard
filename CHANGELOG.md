# Changelog

All notable changes to SolGuard will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Python toolchain pinned to [uv](https://docs.astral.sh/uv/)** as a hard
  project-wide constraint. Pip / poetry / conda are no longer supported as
  primary workflows.
- `skill/solana-security-audit-skill/.python-version` — pins Python 3.11.
- `skill/solana-security-audit-skill/uv.lock` — authoritative dependency
  lockfile (committed).
- `skill/solana-security-audit-skill/README.md` — dedicated uv workflow
  reference (install, sync, run, add, export).
- `skill/solana-security-audit-skill/pyproject.toml` gained `[tool.uv]`,
  `[build-system]`, `[dependency-groups]` and optional `test` / `parser`
  extras, plus explicit runtime dependencies.
- `NOTICE` and `LICENSE-THIRD-PARTY.md` — formal MIT + upstream licence attribution.
- SPDX identifier (`SPDX-License-Identifier: MIT`) block in both READMEs.

### Changed
- `scripts/setup.sh` now hard-fails if `uv` is missing and drives the Python
  bootstrap exclusively through `uv sync --extra test`. `python -m venv`
  + `pip install` code paths removed.
- `scripts/verify-phase1.sh` now checks for `uv`, presence of
  `pyproject.toml` / `.python-version` / `uv.lock`, and runs
  `uv run pytest` (fallback to bare interpreter only with a warning).
- `skill/.../requirements.txt` demoted to a pip-compatible fallback; the
  authoritative source is `pyproject.toml` + `uv.lock`. Regenerate via
  `uv export`.
- Project-management docs updated to codify the uv constraint:
  - `docs/04-SolGuard项目管理/00-项目管理总览.md` (§7.2 key constraints).
  - `docs/04-SolGuard项目管理/02-Phase1-环境搭建与学习.md` (P1.1.1 / P1.1.2 / P1.3.1 / P1.3.2 + FAQ).
  - `docs/04-SolGuard项目管理/03-Phase2-Skill与工具开发.md` (tree-sitter via `uv sync --extra parser`).
  - `docs/04-SolGuard项目管理/06-Phase5-集成与联调.md` (Dockerfile uses the `ghcr.io/astral-sh/uv` multi-stage pattern).
  - `docs/04-SolGuard项目管理/10-风险登记册与应急预案.md` (new **R13** — uv unavailability, 🟡).
  - `docs/04-SolGuard项目管理/11-质量保证与验收计划.md` (regression script, Go/No-Go checklist).
- Both READMEs gained a "Dependency management cheatsheet (Python)" section
  plus explicit uv prerequisites.
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
