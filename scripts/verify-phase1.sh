#!/usr/bin/env bash
# =====================================================
# SolGuard · Phase 1 Verification Script (M0 Gate)
#
# Runs the acceptance checks listed in
#   docs/04-SolGuard项目管理/02-Phase1-环境搭建与学习.md
#   docs/04-SolGuard项目管理/09-里程碑与交付物清单.md  (M0)
#
# Exit code 0 ⇒ Phase 1 passes; non-zero ⇒ failure count.
# =====================================================
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PASS=0
FAIL=0
WARN=0

color()  { printf "\033[%sm%s\033[0m" "$1" "$2"; }
green()  { color "32" "$1"; }
red()    { color "31" "$1"; }
yellow() { color "33" "$1"; }
bold()   { color "1"  "$1"; }

pass() { echo "  $(green "✓") $1"; PASS=$((PASS+1)); }
fail() { echo "  $(red   "✗") $1"; FAIL=$((FAIL+1)); }
warn() { echo "  $(yellow "!") $1"; WARN=$((WARN+1)); }
sect() { echo; echo "$(bold "$1")"; }

# --------------------------------------------------------
sect "1. Tooling"
# --------------------------------------------------------
command -v node >/dev/null && node_v=$(node --version 2>/dev/null || echo n/a)
if [[ "${node_v:-}" =~ ^v(2[0-9]|[3-9][0-9]) ]]; then
  pass "Node.js ${node_v} (>= 20)"
else
  fail "Node.js >= 20 required (found ${node_v:-missing})"
fi

PY_BIN=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    v=$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
    major=$(echo "$v" | cut -d. -f1)
    minor=$(echo "$v" | cut -d. -f2)
    if (( major > 3 )) || (( major == 3 && minor >= 10 )); then
      PY_BIN="$cand"
      PY_VER="$v"
      break
    fi
  fi
done

if [[ -n "$PY_BIN" ]]; then
  pass "Python ${PY_VER} via ${PY_BIN} (>= 3.10)"
else
  fail "Python >= 3.10 required (install python3.10+ or symlink python3 to a newer version)"
  PY_BIN="python3"
fi

if command -v oh >/dev/null; then
  oh_v=$(oh --version 2>/dev/null | head -n1 || echo "?")
  pass "OpenHarness CLI: ${oh_v}"
else
  fail "OpenHarness CLI 'oh' not found (pip install openharness-ai)"
fi

if command -v solana >/dev/null; then
  pass "Solana CLI: $(solana --version 2>/dev/null | head -n1)"
else
  warn "Solana CLI not found (optional for Phase 1 deps, required in Phase 3)"
fi

if command -v git >/dev/null; then
  pass "git: $(git --version 2>/dev/null | awk '{print $3}')"
else
  fail "git not found"
fi

# --------------------------------------------------------
sect "2. Environment files"
# --------------------------------------------------------
[[ -f .env.example ]] && pass ".env.example present" || fail ".env.example missing"
[[ -f .gitignore    ]] && pass ".gitignore present"    || fail ".gitignore missing"
[[ -f LICENSE       ]] && pass "LICENSE present"       || fail "LICENSE missing"
[[ -f README.md     ]] && pass "README.md present"     || fail "README.md missing"
[[ -f .editorconfig ]] && pass ".editorconfig present" || warn ".editorconfig missing"

if [[ -f .env ]]; then
  if grep -qE '^(ANTHROPIC|OPENAI)_API_KEY=.+' .env 2>/dev/null; then
    pass ".env contains an LLM API key"
  else
    warn ".env present but no LLM API key set (ANTHROPIC_API_KEY / OPENAI_API_KEY)"
  fi
else
  warn ".env not created yet (copy from .env.example when ready)"
fi

# --------------------------------------------------------
sect "3. Repository layout"
# --------------------------------------------------------
for d in \
  solguard-server/src \
  skill/solana-security-audit-skill/tools \
  skill/solana-security-audit-skill/core \
  skill/solana-security-audit-skill/references \
  test-fixtures/contracts \
  scripts \
  docs
do
  [[ -d "$d" ]] && pass "dir $d" || fail "dir $d missing"
done

for f in \
  solguard-server/package.json \
  solguard-server/tsconfig.json \
  solguard-server/src/server.ts \
  skill/solana-security-audit-skill/SKILL.md \
  skill/solana-security-audit-skill/core/types.py \
  skill/solana-security-audit-skill/tools/solana_parse.py \
  skill/solana-security-audit-skill/tools/solana_scan.py \
  skill/solana-security-audit-skill/tools/solana_report.py
do
  [[ -f "$f" ]] && pass "file $f" || fail "file $f missing"
done

# --------------------------------------------------------
sect "4. Test fixtures"
# --------------------------------------------------------
fixture_count=$(find test-fixtures/contracts -maxdepth 1 -name '*.rs' -type f 2>/dev/null | wc -l | tr -d ' ')
if (( fixture_count >= 5 )); then
  pass "test fixtures: ${fixture_count} (>= 5)"
else
  fail "test fixtures: ${fixture_count} (expected >= 5)"
fi
[[ -f test-fixtures/README.md ]] && pass "test-fixtures README present" || fail "test-fixtures README missing"
[[ -f test-fixtures/contracts/ground_truth.yaml ]] && pass "ground_truth.yaml present" || fail "ground_truth.yaml missing"

# --------------------------------------------------------
sect "5. Python skill smoke test"
# --------------------------------------------------------
cd skill/solana-security-audit-skill
if PYTHONPATH=. "$PY_BIN" -c "
import json
from core.types import Finding, Severity, Statistics
from tools.solana_parse import parse_source
from tools.solana_scan import scan
from tools.solana_report import build_scan_result, emit
from pathlib import Path

sample = open('../../test-fixtures/contracts/01_missing_signer.rs').read()
parsed = parse_source(sample, '01_missing_signer.rs')
scan_out = scan(parsed, sample)
assert 'findings' in scan_out
assert 'statistics' in scan_out
print('parse_ok=1, scan_ok=1')
" 2>/dev/null; then
  pass "Python skill modules import & execute"
else
  fail "Python skill smoke test failed"
fi
cd "$ROOT"

# --------------------------------------------------------
sect "6. Python pytest"
# --------------------------------------------------------
if (cd skill/solana-security-audit-skill && PYTHONPATH=. "$PY_BIN" -m pytest -q tests/test_types.py >/dev/null 2>&1); then
  pass "pytest core.types passes"
elif (cd skill/solana-security-audit-skill && PYTHONPATH=. "$PY_BIN" -c "import pytest" >/dev/null 2>&1); then
  fail "pytest core.types failed"
else
  warn "pytest not installed (pip install -r skill/solana-security-audit-skill/requirements.txt)"
fi

# --------------------------------------------------------
sect "7. Git repo"
# --------------------------------------------------------
if [[ -d .git ]]; then
  pass "git repo initialized"
  if git remote get-url origin >/dev/null 2>&1; then
    pass "remote origin: $(git remote get-url origin)"
  else
    warn "git remote 'origin' not set"
  fi
else
  fail ".git directory missing"
fi

# --------------------------------------------------------
sect "Summary"
# --------------------------------------------------------
echo "  $(green "Passed"):  ${PASS}"
echo "  $(red   "Failed"):  ${FAIL}"
echo "  $(yellow "Warnings"): ${WARN}"

if (( FAIL == 0 )); then
  echo
  echo "$(green "✅ Phase 1 (M0) PASSED — ready for Phase 2.")"
  exit 0
else
  echo
  echo "$(red "❌ Phase 1 has ${FAIL} failing checks.")"
  exit "${FAIL}"
fi
