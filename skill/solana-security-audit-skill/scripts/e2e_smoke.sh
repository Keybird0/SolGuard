#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
#
# End-to-end smoke test.
#
# Runs scripts/run_audit.py over the five Phase 2 fixtures, writing
# deliverables to <repo_root>/outputs/phase2-baseline/<fixture-stem>/
# and calling scripts/assert_smoke.py on each.
#
# Exit codes:
#   0   every fixture passed ground-truth assertions
#   1   at least one fixture failed
#   2   usage / environment error
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_ROOT/../.." && pwd)"
FIXTURES_DIR="$REPO_ROOT/test-fixtures/contracts"
OUTPUT_ROOT="${OUTPUT_ROOT:-$REPO_ROOT/outputs/phase2-baseline}"
GROUND_TRUTH="$FIXTURES_DIR/ground_truth.yaml"

FIXTURES=(
  "01_missing_signer"
  "02_missing_owner"
  "03_integer_overflow"
  "04_arbitrary_cpi"
  "05_clean_contract"
)

mkdir -p "$OUTPUT_ROOT"
cd "$SKILL_ROOT"

fail=0
for name in "${FIXTURES[@]}"; do
  fx="$FIXTURES_DIR/$name.rs"
  if [ ! -f "$fx" ]; then
    echo "[e2e] missing fixture: $fx" >&2
    exit 2
  fi
  echo "[e2e] === $name ==="
  uv run python scripts/run_audit.py "$fx" \
    --output-root "$OUTPUT_ROOT" \
    --task-id "$name"

  uv run python scripts/assert_smoke.py \
    "$OUTPUT_ROOT/$name" \
    "$GROUND_TRUTH" \
    "$name.rs" \
    || fail=1
done

if [ "$fail" -ne 0 ]; then
  echo "[e2e] FAIL: at least one fixture failed assertions" >&2
  exit 1
fi
echo "[e2e] ALL PASS"
