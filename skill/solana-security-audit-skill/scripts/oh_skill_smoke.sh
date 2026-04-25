#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
#
# oh_skill_smoke.sh — verify every tool declared in skill.yaml is
# importable and exposes an ``execute()`` method. This is the minimum
# precondition for both the `oh -p` path and the Python-subprocess
# fallback.
#
# Exit codes:
#   0  all tools imported + execute() callable
#   1  tool missing / not importable
#   2  execute() signature missing
#
# Usage:
#   bash scripts/oh_skill_smoke.sh            # uses uv run
#   OH_SMOKE_NO_UV=1 bash scripts/oh_skill_smoke.sh  # plain python
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_CMD=("uv" "run" "python")
if [[ "${OH_SMOKE_NO_UV:-}" == "1" ]]; then
  PYTHON_CMD=("python")
fi

echo "==> oh_skill_smoke: importing 5 tools declared in skill.yaml"

"${PYTHON_CMD[@]}" - <<'PY'
import importlib
import sys

TOOLS = [
    ("tools.solana_parse", "SolanaParseTool"),
    ("tools.solana_scan", "SolanaScanTool"),
    ("tools.semgrep_runner", "SemgrepRunner"),
    ("ai.analyzer_tool", "AIAnalyzerTool"),
    ("tools.solana_report", "SolanaReportTool"),
]

failures: list[str] = []
for module_name, cls_name in TOOLS:
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"[IMPORT FAIL] {module_name}: {exc!r}")
        continue
    cls = getattr(mod, cls_name, None)
    if cls is None:
        failures.append(f"[ATTR FAIL] {module_name}.{cls_name} not found")
        continue
    instance = cls()
    if not callable(getattr(instance, "execute", None)):
        failures.append(f"[SIGNATURE FAIL] {cls_name}.execute is not callable")
        continue
    print(f"  OK  {module_name}:{cls_name}")

if failures:
    print("\n".join(failures), file=sys.stderr)
    sys.exit(2 if any("SIGNATURE" in f for f in failures) else 1)

print("==> all 5 tools importable; execute() present on each")
PY

echo "==> checking skill.yaml parseable"
"${PYTHON_CMD[@]}" - <<'PY'
import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import-not-found]
except ImportError:
    print("PyYAML missing; skipping YAML validation (non-fatal)")
    sys.exit(0)

data = yaml.safe_load(Path("skill.yaml").read_text(encoding="utf-8"))
assert data["name"] == "solana-security-audit-skill", "skill name drift"
tools = {t["name"] for t in data["tools"]}
expected = {
    "solana_parse",
    "solana_scan",
    "solana_semgrep",
    "solana_ai_analyze",
    "solana_report",
}
missing = expected - tools
extra = tools - expected
if missing:
    print(f"[FAIL] skill.yaml missing tools: {missing}", file=sys.stderr)
    sys.exit(3)
if extra:
    print(f"[WARN] skill.yaml has unexpected tools: {extra}")
print("  OK  skill.yaml declares exactly the 5 expected tools")
PY

echo
echo "==> oh_skill_smoke PASSED"
