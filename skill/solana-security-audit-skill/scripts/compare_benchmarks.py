#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Compare two ``run_benchmark.py`` output directories side-by-side.

Usage::

    uv run python scripts/compare_benchmarks.py \
        --baseline outputs/phase6-baseline \
        --candidates outputs/phase6-round1-scan outputs/phase6-round2-prompt \
        --output outputs/phase6-comparison.md

Produces a single Markdown report with:

* Aggregate precision / recall / F1 / avg duration delta vs baseline for
  each candidate.
* Per-scale (small/medium/large) table.
* Per-fixture status transitions (``TP→FN``, ``FP→cleared`` …) so
  reviewers can see exactly where a tuning round helped or hurt.
* Regression column: fixtures that were strictly worse than baseline.

Exit codes:
    0 — report produced (regressions may still exist; surfaced in report)
    2 — usage error / missing summary.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_run(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.json missing in {run_dir}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    per_fx: dict[str, dict[str, Any]] = {}
    pf_dir = run_dir / "per-fixture"
    if pf_dir.is_dir():
        for f in sorted(pf_dir.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            per_fx[data["name"]] = data
    return {"summary": summary, "per_fixture": per_fx, "path": str(run_dir)}


def _fmt_delta(current: float, baseline: float) -> str:
    d = current - baseline
    if abs(d) < 1e-9:
        return "±0.0000"
    return f"{'+' if d > 0 else ''}{d:.4f}"


def _fx_status(fx: dict[str, Any]) -> str:
    tp, fp, fn = len(fx["tp"]), len(fx["fp"]), len(fx["fn"])
    dec = fx["decision"]
    return f"{dec}|TP={tp} FP={fp} FN={fn}"


def _compare_fixture(base_fx: dict[str, Any], cand_fx: dict[str, Any]) -> dict[str, Any]:
    b_tp, b_fp, b_fn = len(base_fx["tp"]), len(base_fx["fp"]), len(base_fx["fn"])
    c_tp, c_fp, c_fn = len(cand_fx["tp"]), len(cand_fx["fp"]), len(cand_fx["fn"])
    # Strict regression: candidate has >= baseline FN *and* >= baseline FP
    # while TP did not strictly improve.
    regressed = (c_fn > b_fn) or (c_fp > b_fp and c_tp <= b_tp)
    improved = (c_tp > b_tp) or (c_fp < b_fp) or (c_fn < b_fn)
    return {
        "name": base_fx["name"],
        "baseline": (b_tp, b_fp, b_fn),
        "candidate": (c_tp, c_fp, c_fn),
        "delta_dur_s": cand_fx["duration_s"] - base_fx["duration_s"],
        "regressed": regressed and not improved,
        "improved": improved and not regressed,
    }


def _render(baseline: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    base_sum = baseline["summary"]
    lines: list[str] = []
    lines.append("# Benchmark Comparison")
    lines.append("")
    lines.append(f"- Baseline: `{base_sum.get('tag','?')}` · `{baseline['path']}`")
    for cand in candidates:
        lines.append(
            f"- Candidate: `{cand['summary'].get('tag','?')}` · `{cand['path']}`"
        )
    lines.append("")

    # Aggregate table
    lines.extend([
        "## Aggregate (overall)",
        "",
        "| Run | Fixtures | TP | FP | FN | Precision | Recall | F1 | Avg dur(s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    b = base_sum["overall"]
    lines.append(
        f"| baseline `{base_sum.get('tag','?')}` | {b['fixture_count']} "
        f"| {b['tp']} | {b['fp']} | {b['fn']} "
        f"| {b['precision']} | {b['recall']} | {b['f1']} | {b['avg_duration_s']} |"
    )
    for cand in candidates:
        c = cand["summary"]["overall"]
        lines.append(
            f"| `{cand['summary'].get('tag','?')}` | {c['fixture_count']} "
            f"| {c['tp']} | {c['fp']} | {c['fn']} "
            f"| {c['precision']} ({_fmt_delta(c['precision'], b['precision'])}) "
            f"| {c['recall']} ({_fmt_delta(c['recall'], b['recall'])}) "
            f"| {c['f1']} ({_fmt_delta(c['f1'], b['f1'])}) "
            f"| {c['avg_duration_s']} ({_fmt_delta(c['avg_duration_s'], b['avg_duration_s'])}) |"
        )
    lines.append("")

    # Per scale
    lines.extend(["## Per scale", ""])
    for scale in ("small", "medium", "large"):
        lines.extend([
            f"### {scale}",
            "",
            "| Run | Fixtures | TP | FP | FN | Precision | Recall | F1 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ])
        bs = base_sum["per_scale"][scale]
        lines.append(
            f"| baseline | {bs['fixture_count']} | {bs['tp']} | {bs['fp']} | {bs['fn']} "
            f"| {bs['precision']} | {bs['recall']} | {bs['f1']} |"
        )
        for cand in candidates:
            cs = cand["summary"]["per_scale"][scale]
            lines.append(
                f"| `{cand['summary'].get('tag','?')}` | {cs['fixture_count']} "
                f"| {cs['tp']} | {cs['fp']} | {cs['fn']} "
                f"| {cs['precision']} ({_fmt_delta(cs['precision'], bs['precision'])}) "
                f"| {cs['recall']} ({_fmt_delta(cs['recall'], bs['recall'])}) "
                f"| {cs['f1']} ({_fmt_delta(cs['f1'], bs['f1'])}) |"
            )
        lines.append("")

    # Per-fixture transitions
    lines.extend(["## Per-fixture transitions", ""])
    lines.append("Status = `decision|TP=n FP=n FN=n`. Rows with regression flagged.")
    lines.append("")
    header_tags = " | ".join(c["summary"].get("tag", "?") for c in candidates)
    lines.append(f"| Fixture | baseline | {header_tags} | verdict |")
    lines.append("|---|---|" + "---|" * len(candidates) + "---|")

    # One row per fixture
    all_names = sorted(baseline["per_fixture"].keys())
    regression_rows: list[str] = []
    for name in all_names:
        base_fx = baseline["per_fixture"][name]
        row = [f"`{name}`", _fx_status(base_fx)]
        any_regress = False
        any_improve = False
        for cand in candidates:
            cand_fx = cand["per_fixture"].get(name)
            if cand_fx is None:
                row.append("—")
                continue
            cmp = _compare_fixture(base_fx, cand_fx)
            marker = ""
            if cmp["regressed"]:
                marker, any_regress = " ⚠️", True
            elif cmp["improved"]:
                marker, any_improve = " ✓", True
            row.append(f"{_fx_status(cand_fx)}{marker}")
        verdict = "regress" if any_regress else ("improve" if any_improve else "same")
        row.append(verdict)
        rendered = "| " + " | ".join(row) + " |"
        lines.append(rendered)
        if any_regress:
            regression_rows.append(rendered)

    lines.append("")

    # Regression subsection (always emitted so CI can grep for it)
    lines.extend(["## Regressions vs baseline", ""])
    if regression_rows:
        lines.append(f"⚠️ {len(regression_rows)} fixture(s) regressed:")
        lines.append("")
        lines.extend(regression_rows)
    else:
        lines.append("✅ No regressions detected.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--baseline", required=True, help="Baseline run directory")
    parser.add_argument(
        "--candidates",
        required=True,
        nargs="+",
        help="One or more candidate run directories",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Destination Markdown file",
    )
    args = parser.parse_args()

    try:
        baseline = _load_run(Path(args.baseline))
        cands = [_load_run(Path(p)) for p in args.candidates]
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = _render(baseline, cands)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"[compare_benchmarks] wrote {out_path}")
    # Quick stdout summary
    b = baseline["summary"]["overall"]
    for c in cands:
        o = c["summary"]["overall"]
        tag = c["summary"].get("tag", "?")
        print(
            f"  {tag}: P={o['precision']} ({_fmt_delta(o['precision'], b['precision'])}) "
            f"R={o['recall']} ({_fmt_delta(o['recall'], b['recall'])}) "
            f"F1={o['f1']} ({_fmt_delta(o['f1'], b['f1'])})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
