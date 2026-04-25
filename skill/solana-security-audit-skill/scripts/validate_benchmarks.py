#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Validate ``test-fixtures/benchmark.yaml`` shape + file existence.

Runs before ``run_benchmark.py`` to fail fast on schema drift or broken
fixture paths. Designed to be safe in CI (no network, no LLM calls).

Exit codes:
    0 — all checks pass
    1 — at least one validation error
    2 — usage / missing file
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

# Seven canonical rule ids the scanner emits. `semgrep:` prefix is also
# allowed (matches what AIAnalyzer produces).
CANONICAL_RULE_IDS: set[str] = {
    "missing_signer_check",
    "missing_owner_check",
    "integer_overflow",
    "arbitrary_cpi",
    "account_data_matching",
    "pda_derivation_error",
    "uninitialized_account",
}
VALID_SEVERITIES: set[str] = {"Critical", "High", "Medium", "Low", "Info"}
VALID_SCALES: set[str] = {"small", "medium", "large"}
REQUIRED_TOP: set[str] = {"version", "fixtures"}
REQUIRED_FIXTURE_KEYS: set[str] = {
    "name",
    "path",
    "scale",
    "has_vuln",
    "source",
    "ground_truth",
}


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"PASS: {msg}")


def _is_valid_rule(rule_id: str) -> bool:
    if rule_id in CANONICAL_RULE_IDS:
        return True
    if rule_id.startswith("semgrep:") and len(rule_id) > len("semgrep:"):
        return True
    return False


def validate(benchmark_path: Path) -> int:
    if not benchmark_path.exists():
        _fail(f"benchmark.yaml not found: {benchmark_path}")
        return 2

    try:
        data: Any = yaml.safe_load(benchmark_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        _fail(f"invalid YAML: {exc}")
        return 1

    errors: list[str] = []

    if not isinstance(data, dict):
        _fail("top-level must be a mapping")
        return 1

    missing_top = REQUIRED_TOP - set(data.keys())
    if missing_top:
        errors.append(f"missing top-level keys: {sorted(missing_top)}")

    fixtures = data.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        _fail("fixtures must be a non-empty list")
        return 1

    root = benchmark_path.parent
    seen_names: set[str] = set()
    has_vuln_true = 0
    has_vuln_false = 0

    for idx, fx in enumerate(fixtures):
        label = f"fixtures[{idx}]"
        if not isinstance(fx, dict):
            errors.append(f"{label}: entry must be a mapping")
            continue
        missing = REQUIRED_FIXTURE_KEYS - set(fx.keys())
        if missing:
            errors.append(f"{label}: missing keys {sorted(missing)}")

        name = fx.get("name", f"<idx-{idx}>")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{label}: name must be non-empty string")
        elif name in seen_names:
            errors.append(f"{label}: duplicate name '{name}'")
        else:
            seen_names.add(name)

        path_str = fx.get("path", "")
        if isinstance(path_str, str) and path_str:
            p = (root / path_str).resolve()
            if not p.is_file():
                errors.append(f"{label} ({name}): path not found: {path_str}")
            elif not path_str.endswith(".rs"):
                errors.append(f"{label} ({name}): path must end with .rs")
        else:
            errors.append(f"{label}: path missing / not string")

        scale = fx.get("scale")
        if scale not in VALID_SCALES:
            errors.append(
                f"{label} ({name}): scale={scale!r} not one of {sorted(VALID_SCALES)}"
            )

        has_vuln = fx.get("has_vuln")
        if not isinstance(has_vuln, bool):
            errors.append(f"{label} ({name}): has_vuln must be bool")
        elif has_vuln:
            has_vuln_true += 1
        else:
            has_vuln_false += 1

        source = fx.get("source")
        if not isinstance(source, dict) or {"repo", "commit", "license"} - set(
            source.keys()
        ):
            errors.append(
                f"{label} ({name}): source must contain repo/commit/license"
            )

        gt = fx.get("ground_truth")
        if not isinstance(gt, list):
            errors.append(f"{label} ({name}): ground_truth must be list (may be [])")
            continue

        if has_vuln is True and not gt:
            errors.append(
                f"{label} ({name}): has_vuln=true but ground_truth is empty"
            )
        if has_vuln is False and gt:
            errors.append(
                f"{label} ({name}): has_vuln=false must have empty ground_truth"
            )

        for gt_idx, entry in enumerate(gt):
            glabel = f"{label} ({name}).ground_truth[{gt_idx}]"
            if not isinstance(entry, dict):
                errors.append(f"{glabel}: entry must be a mapping")
                continue
            rule_id = entry.get("rule_id", "")
            if not isinstance(rule_id, str) or not _is_valid_rule(rule_id):
                errors.append(f"{glabel}: rule_id={rule_id!r} not recognized")
            sev = entry.get("severity", "")
            if sev not in VALID_SEVERITIES:
                errors.append(f"{glabel}: severity={sev!r} invalid")
            line = entry.get("approx_line")
            if not isinstance(line, int) or line <= 0:
                errors.append(f"{glabel}: approx_line must be positive int")

    # Aggregate floors (DoD: has_vuln=true >= 5, has_vuln=false >= 3).
    if has_vuln_true < 5:
        errors.append(
            f"aggregate: has_vuln=true count {has_vuln_true} < 5 (DoD floor)"
        )
    else:
        _ok(f"has_vuln=true count {has_vuln_true} >= 5")
    if has_vuln_false < 3:
        errors.append(
            f"aggregate: has_vuln=false count {has_vuln_false} < 3 (DoD floor)"
        )
    else:
        _ok(f"has_vuln=false count {has_vuln_false} >= 3")
    if len(fixtures) < 15:
        errors.append(f"aggregate: total fixtures {len(fixtures)} < 15 (DoD floor)")
    else:
        _ok(f"total fixtures {len(fixtures)} >= 15")

    # Optional: counts: block matches actual values.
    counts = data.get("counts")
    if isinstance(counts, dict):
        if counts.get("total") != len(fixtures):
            errors.append(
                f"counts.total={counts.get('total')} != actual {len(fixtures)}"
            )
        if counts.get("has_vuln_true") != has_vuln_true:
            errors.append(
                f"counts.has_vuln_true={counts.get('has_vuln_true')} "
                f"!= actual {has_vuln_true}"
            )
        if counts.get("has_vuln_false") != has_vuln_false:
            errors.append(
                f"counts.has_vuln_false={counts.get('has_vuln_false')} "
                f"!= actual {has_vuln_false}"
            )

    if errors:
        print("\n".join(f"FAIL: {e}" for e in errors), file=sys.stderr)
        return 1

    _ok(f"benchmark.yaml valid: {len(fixtures)} fixtures")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: validate_benchmarks.py <benchmark.yaml>", file=sys.stderr)
        return 2
    return validate(Path(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
