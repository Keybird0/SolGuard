#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
#
# Degraded-mode E2E smoke test.
#
# Forces the AI layer to fall back to degraded mode (via --degraded, and by
# intentionally unsetting any live API key) and verifies that:
#
#   1. All 5 fixtures still produce 3 Markdown + report.json artefacts.
#   2. risk_summary.md begins with the "DEGRADED — LLM unavailable" banner.
#   3. decision=="degraded" inside report.json.
#
# Output lands in <repo_root>/outputs/phase2-baseline-degraded/ to avoid
# overwriting the live-mode baseline.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_ROOT/../.." && pwd)"
FIXTURES_DIR="$REPO_ROOT/test-fixtures/contracts"
OUTPUT_ROOT="${OUTPUT_ROOT:-$REPO_ROOT/outputs/phase2-baseline-degraded}"
GROUND_TRUTH="$FIXTURES_DIR/ground_truth.yaml"

FIXTURES=(
  "01_missing_signer"
  "02_missing_owner"
  "03_integer_overflow"
  "04_arbitrary_cpi"
  "05_clean_contract"
)

unset ANTHROPIC_API_KEY || true
unset OPENAI_API_KEY || true
mkdir -p "$OUTPUT_ROOT"
cd "$SKILL_ROOT"

fail=0
for name in "${FIXTURES[@]}"; do
  fx="$FIXTURES_DIR/$name.rs"
  echo "[e2e-degraded] === $name ==="
  uv run python scripts/run_audit.py "$fx" \
    --output-root "$OUTPUT_ROOT" \
    --task-id "$name" \
    --degraded

  uv run python scripts/assert_smoke.py \
    "$OUTPUT_ROOT/$name" \
    "$GROUND_TRUTH" \
    "$name.rs" \
    || fail=1
done

if [ "$fail" -ne 0 ]; then
  echo "[e2e-degraded] FAIL: at least one fixture failed degraded assertions" >&2
  exit 1
fi
echo "[e2e-degraded] ALL PASS"
