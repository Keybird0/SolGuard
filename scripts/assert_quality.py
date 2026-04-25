#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Phase 6 · quality-gate asserter.

Consumes `outputs/benchmark-*/summary.json` (produced by
`scripts/run_benchmark.py`) and hard-fails when the M4 gates
(Precision >= 0.8, Recall >= 0.8, F1 >= 0.8) are not met.

Designed to run in CI once M3 (public deployment) lands, but safe and
useful today for local verification:

    python scripts/assert_quality.py outputs/benchmark-round2-prompt/summary.json

Extra flags let us relax gates for diagnostic runs:

    --min-precision / --min-recall / --min-f1  (defaults 0.8 / 0.8 / 0.8)
    --max-avg-seconds                            (default 300, M4 = "<= 5 min")
    --allow-degraded                             # tolerate LLM-unavailable runs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_summary(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"error: summary file not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: summary file is not valid JSON: {exc}") from exc


def _check(
    label: str, actual: float, minimum: float, *, higher_is_better: bool = True
) -> tuple[bool, str]:
    ok = actual >= minimum if higher_is_better else actual <= minimum
    sym = "OK" if ok else "FAIL"
    op = ">=" if higher_is_better else "<="
    return ok, f"[{sym}] {label}: {actual:.4f} {op} {minimum:.4f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("summary_file", help="Path to run_benchmark.py summary.json")
    parser.add_argument("--min-precision", type=float, default=0.80)
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument("--min-f1", type=float, default=0.80)
    parser.add_argument(
        "--max-avg-seconds",
        type=float,
        default=300.0,
        help="M4 gate: per-fixture average audit time <= 5 min",
    )
    parser.add_argument(
        "--allow-degraded",
        action="store_true",
        help="Do not fail when degraded_count > 0 (LLM unavailable runs)",
    )
    args = parser.parse_args()

    summary = _load_summary(Path(args.summary_file))
    # run_benchmark.py writes metrics under `overall`; older or CI-
    # generated shapes flatten them at the root or nest them under
    # `aggregate`. Support all three.
    agg = summary.get("overall") or summary.get("aggregate") or summary

    precision = float(agg.get("precision", 0.0))
    recall = float(agg.get("recall", 0.0))
    f1 = float(agg.get("f1", 0.0))
    avg_sec = float(
        agg.get("avg_duration_s")
        or agg.get("avg_seconds")
        or agg.get("avg_time_sec")
        or 0.0
    )
    degraded = int(summary.get("degraded_count", agg.get("degraded_count", 0)))

    results: list[tuple[bool, str]] = []
    results.append(_check("precision", precision, args.min_precision))
    results.append(_check("recall", recall, args.min_recall))
    results.append(_check("f1", f1, args.min_f1))
    if avg_sec > 0:
        results.append(
            _check(
                "avg_seconds",
                avg_sec,
                args.max_avg_seconds,
                higher_is_better=False,
            )
        )
    if not args.allow_degraded and degraded > 0:
        results.append((False, f"[FAIL] degraded_count: {degraded} (expect 0)"))

    all_ok = all(ok for ok, _ in results)
    print(
        "\n".join(msg for _, msg in results)
        + f"\n---\nOverall: {'PASS' if all_ok else 'FAIL'}"
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
