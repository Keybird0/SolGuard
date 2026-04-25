#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Assert a smoke-run output directory matches ground_truth.yaml.

Usage::

    python scripts/assert_smoke.py \
        <output_dir> \
        <ground_truth.yaml> \
        [<fixture_file_name>]

If ``fixture_file_name`` is omitted, the script re-reads ``report.json`` and
uses ``contract_name``.

Exit codes::

    0   all assertions pass
    1   at least one assertion failed
    2   usage error / file not found

The assertions are intentionally tolerant of degraded mode so we can reuse
the script from ``scripts/e2e_smoke_degraded.sh``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

_THIS = Path(__file__).resolve()
_SKILL_ROOT = _THIS.parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from core.types import ScanResult  # noqa: E402


REQUIRED_FILES = ("risk_summary.md", "assessment.md", "checklist.md", "report.json")


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"PASS: {msg}")


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: assert_smoke.py <output_dir> <ground_truth.yaml> "
            "[<fixture.rs>]",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(sys.argv[1])
    truth_path = Path(sys.argv[2])
    fixture_name = sys.argv[3] if len(sys.argv) >= 4 else None

    if not out_dir.is_dir():
        _fail(f"output directory not found: {out_dir}")
        return 2
    if not truth_path.exists():
        _fail(f"ground truth not found: {truth_path}")
        return 2

    errors: list[str] = []

    # 1) Required files on disk ---------------------------------------------
    for name in REQUIRED_FILES:
        if not (out_dir / name).exists():
            errors.append(f"missing artefact {name} in {out_dir}")
        else:
            _ok(f"found {name}")

    # 2) report.json parses through ScanResult ------------------------------
    report_path = out_dir / "report.json"
    sr: ScanResult | None = None
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            sr = ScanResult.from_dict(data)
            _ok(f"report.json round-trips via ScanResult (decision={sr.decision})")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"report.json invalid: {exc}")

    # 3) Ground truth cross-check -------------------------------------------
    if sr is not None:
        fixture_key = fixture_name or f"{Path(sr.contract_name).stem}.rs"
        truth = yaml.safe_load(truth_path.read_text(encoding="utf-8"))
        entry = next(
            (
                e
                for e in truth.get("fixtures", [])
                if e.get("file") == fixture_key
                or e.get("file") == f"{sr.contract_name}.rs"
            ),
            None,
        )
        if entry is None:
            print(
                f"INFO: no ground truth entry for {fixture_key} — skipping "
                "expected_scan_rule_ids check.",
            )
        else:
            expected_scan = set(entry.get("expected_scan_rule_ids", []))
            actual_rules = {f.rule_id or "" for f in sr.findings}
            missing = expected_scan - actual_rules
            if sr.decision == "degraded":
                # In degraded mode scan hints are the only evidence; we only
                # check that the rule ids match (no AI-confirmed floor).
                if missing:
                    errors.append(
                        f"degraded: missing expected scan rule ids {missing} "
                        f"(actual={actual_rules})"
                    )
                else:
                    _ok(
                        f"degraded: scan rule ids {expected_scan} all present"
                    )
            else:
                # Non-degraded: enforce confirmed-findings floor.
                minimum = entry.get("expected_ai_confirmed_min")
                if missing:
                    errors.append(
                        f"scan rule ids missing from findings: {missing} "
                        f"(actual={actual_rules})"
                    )
                else:
                    _ok(f"scan rule ids {expected_scan} all present")
                if (
                    isinstance(minimum, int)
                    and len(sr.findings) < minimum
                ):
                    errors.append(
                        f"expected_ai_confirmed_min={minimum} but got "
                        f"{len(sr.findings)} findings"
                    )
                elif isinstance(minimum, int):
                    _ok(
                        f"findings count {len(sr.findings)} ≥ "
                        f"expected_ai_confirmed_min {minimum}"
                    )

    # 4) Degraded banner check ----------------------------------------------
    if sr is not None and sr.decision == "degraded":
        body = (out_dir / "risk_summary.md").read_text(encoding="utf-8")
        if "DEGRADED" not in body:
            errors.append(
                "decision=degraded but risk_summary.md has no DEGRADED banner"
            )
        else:
            _ok("DEGRADED banner present in risk_summary.md")

    if errors:
        print("\n".join(f"FAIL: {e}" for e in errors), file=sys.stderr)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
