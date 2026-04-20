#!/usr/bin/env bash
# =====================================================
# SolGuard · One-shot setup
#
# - Copies .env.example → .env (if missing)
# - Installs Node deps for solguard-server
# - Creates the managed Python venv for the skill via `uv sync`
#
# NOTE: Python dependencies are managed with uv (see
# skill/solana-security-audit-skill/README.md). pip/venv is a fallback
# only — this script refuses to fall back silently.
# =====================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> SolGuard setup starting at $ROOT"

# ---------------------------------------------------------------- .env
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "   created .env — fill in secrets before running the server."
else
  echo "   .env already exists (skipped)."
fi

# ------------------------------------------------------------- Node deps
echo "==> Installing Node dependencies (solguard-server)"
if command -v npm >/dev/null; then
  (cd solguard-server && npm install --silent)
  echo "   solguard-server deps installed."
else
  echo "   WARN: npm not found; skip Node deps."
fi

# --------------------------------------------------------- Python via uv
echo "==> Setting up Python environment via uv (skill)"
if ! command -v uv >/dev/null 2>&1; then
  cat <<'EOF'
   ERROR: uv is not installed but required by SolGuard.

   Install it first:

       curl -LsSf https://astral.sh/uv/install.sh | sh
       # or
       brew install uv

   Then re-run:  bash scripts/setup.sh
EOF
  exit 2
fi

echo "   uv: $(uv --version)"
(
  cd skill/solana-security-audit-skill
  # `uv sync` reads .python-version + pyproject.toml + uv.lock, downloads
  # a matching interpreter if needed, creates .venv, and installs everything.
  uv sync --extra test
)
echo "   Python env ready at skill/solana-security-audit-skill/.venv"

# ------------------------------------------------------------ verify M0
echo "==> Running Phase 1 verification"
bash scripts/verify-phase1.sh || {
  echo "!! Phase 1 verification reported issues — fix them before proceeding."
  exit 1
}

cat <<EOF

Setup complete.

Next steps:
  1. Edit .env with your LLM API key and SMTP / wallet details.
  2. Start the backend:
       cd solguard-server && npm run dev
  3. Run commands inside the skill env (no activate needed):
       cd skill/solana-security-audit-skill
       uv run pytest
       uv run ruff check .
  4. Phase 2 tasks begin in:
       docs/04-SolGuard项目管理/03-Phase2-Skill与工具开发.md
EOF
