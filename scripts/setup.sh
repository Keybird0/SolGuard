#!/usr/bin/env bash
# =====================================================
# SolGuard · One-shot setup
#
# - Copies .env.example → .env (if missing)
# - Installs Node deps for solguard-server
# - Creates Python venv and installs skill deps
# =====================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> SolGuard setup starting at $ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "   created .env — fill in secrets before running the server."
else
  echo "   .env already exists (skipped)."
fi

echo "==> Installing Node dependencies"
if command -v npm >/dev/null; then
  (cd solguard-server && npm install --silent)
  echo "   solguard-server deps installed."
else
  echo "   WARN: npm not found; skip Node deps."
fi

echo "==> Setting up Python virtualenv for the skill"
PY_BIN=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    v=$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
    major=${v%.*}; minor=${v#*.}
    if (( major > 3 )) || (( major == 3 && minor >= 10 )); then
      PY_BIN="$cand"; break
    fi
  fi
done

if [[ -n "$PY_BIN" ]]; then
  cd skill/solana-security-audit-skill
  if [[ ! -d .venv ]]; then
    "$PY_BIN" -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
  deactivate
  cd "$ROOT"
  echo "   Python venv ready at skill/solana-security-audit-skill/.venv"
else
  echo "   WARN: python3 not found; skip Python setup."
fi

echo "==> Running Phase 1 verification"
bash scripts/verify-phase1.sh || {
  echo "!! Phase 1 verification reported issues — fix them before proceeding."
  exit 1
}

cat <<EOF

Setup complete.

Next steps:
  1. Edit .env with your LLM API key and SMTP / wallet details.
  2. Start the backend:   cd solguard-server && npm run dev
  3. Activate the skill venv: source skill/solana-security-audit-skill/.venv/bin/activate
  4. Phase 2 tasks begin in: docs/04-SolGuard项目管理/03-Phase2-Skill与工具开发.md
EOF
