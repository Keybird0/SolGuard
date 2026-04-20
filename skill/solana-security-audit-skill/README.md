# solana-security-audit-skill

OpenHarness skill that powers SolGuard's audit pipeline
(Parse → Scan → AI → Kill-Signal → Report). See
[`SKILL.md`](./SKILL.md) for the 7-step audit SOP.

---

## Python tooling — **uv is the canonical workflow**

This package is managed with [**uv**](https://docs.astral.sh/uv/). All
Python operations (env creation, dep install, running tests, building
the skill wheel) MUST go through `uv` so behaviour is reproducible
across machines and CI.

- Python version is pinned in [`.python-version`](./.python-version) (3.11).
- Runtime, optional and dev dependencies live in [`pyproject.toml`](./pyproject.toml).
- The authoritative dependency graph is captured in `uv.lock` (checked in).
- `requirements.txt` is a pip-compatible fallback, **not** the source of truth.

### Install uv (once per machine)

```bash
# Recommended installer
curl -LsSf https://astral.sh/uv/install.sh | sh

# or via Homebrew
brew install uv
```

### Standard commands

```bash
# cd into this package first
cd skill/solana-security-audit-skill

# 1. Create / sync the virtualenv with runtime + dev deps
uv sync

# 2. Add the optional test extra (pytest) or tree-sitter parser (Phase 6)
uv sync --extra test
uv sync --extra parser

# 3. Run anything inside the managed venv (no activate needed)
uv run pytest -q
uv run ruff check .
uv run black --check .
uv run mypy core/ tools/ ai/ reporters/
uv run python -m tools.solana_scan --help

# 4. Add / remove dependencies
uv add httpx
uv add --dev pytest-mock
uv remove tenacity

# 5. Refresh the lockfile without syncing
uv lock

# 6. Export for pip-only environments
uv export --format requirements-txt --no-hashes --no-dev > requirements.txt
```

### Do NOT

- Create `venv/` with `python -m venv` by hand.
- `pip install -r requirements.txt` for daily dev — use `uv sync`.
- Edit `uv.lock` manually — let `uv` regenerate it.

---

## Directory map

```
solana-security-audit-skill/
├── SKILL.md                # 7-step audit SOP + JSON schema
├── .python-version         # uv-managed Python version (3.11)
├── pyproject.toml          # deps + tool configs (uv / ruff / mypy / pytest)
├── uv.lock                 # locked dep graph (commit this)
├── requirements.txt        # pip fallback (generated from uv)
├── core/                   # shared types (Finding, ScanResult, …)
├── tools/                  # solana_parse · solana_scan · solana_report
│   └── rules/              # 7 Solana security rules
├── ai/                     # LLM analyzer + prompts
├── reporters/              # Markdown report templates
├── references/             # vulnerability patterns / workflow / templates
├── scripts/                # utility scripts (audit bundle builder, …)
└── tests/                  # pytest tests
```

---

## Linked docs

- Phase 2 roadmap: `../../docs/04-SolGuard项目管理/03-Phase2-Skill与工具开发.md`
- Rule catalogue: [`references/vulnerability-patterns.md`](./references/vulnerability-patterns.md)
- Best practices: [`references/best-practices.md`](./references/best-practices.md)
