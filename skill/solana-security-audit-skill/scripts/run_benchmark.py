#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Benchmark driver for Phase 6 accuracy + performance measurement.

Reads ``test-fixtures/benchmark.yaml``, runs the in-process SolGuard
pipeline (parse → scan → semgrep → AI → report) over every fixture with
bounded concurrency, and emits a summary suitable for M4 gating and for
``compare_benchmarks.py``.

Outputs (under ``--output``)::

    per-fixture/
        <fixture_name>.json        # {finding_rows, duration_s, tp/fp/fn lists}
    summary.json                   # aggregate precision/recall/F1 + per-scale
    summary.md                     # human-readable table
    run.log                        # flat log of every fixture lifecycle event

Usage::

    uv run python scripts/run_benchmark.py \
        --benchmark ../../test-fixtures/benchmark.yaml \
        --output outputs/phase6-baseline \
        --tag baseline \
        --concurrency 5

TP/FP/FN rules (in line with Phase 6 DoD)
----------------------------------------
*  For each ground_truth entry ``(rule_id, approx_line)`` we look for a
   finding whose ``rule_id`` matches (canonical ids only; ``semgrep:`` is
   normalized to its base) and whose location line is within ±5 of
   ``approx_line``. Match → **TP**; miss → **FN**.
*  Any finding that doesn't match a ground_truth entry → **FP** (unless the
   fixture has ``has_vuln=false`` and findings=[], then precision / recall
   are both defined as 1.0).
*  Clean fixtures (``has_vuln=false``): any finding is FP. A totally empty
   findings list is a TN (increments precision denominator-free).

Aggregate::

    precision = Σ TP / (Σ TP + Σ FP)
    recall    = Σ TP / (Σ TP + Σ FN)
    f1        = 2 * precision * recall / (precision + recall)

Degraded mode (``decision="degraded"``) findings still count, but degraded
runs are tagged in per-fixture so compare_benchmarks.py can filter.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_THIS = Path(__file__).resolve()
_SKILL_ROOT = _THIS.parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from scripts.run_audit import run_audit  # noqa: E402


LINE_TOLERANCE = 5


@dataclass
class FixtureResult:
    name: str
    path: str
    scale: str
    has_vuln: bool
    duration_s: float
    decision: str
    findings: list[dict[str, Any]]
    tp: list[dict[str, Any]] = field(default_factory=list)
    fp: list[dict[str, Any]] = field(default_factory=list)
    fn: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "scale": self.scale,
            "has_vuln": self.has_vuln,
            "duration_s": self.duration_s,
            "decision": self.decision,
            "finding_count": len(self.findings),
            "findings": self.findings,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "error": self.error,
        }


def _normalize_rule_id(rule_id: str | None) -> str:
    if not rule_id:
        return ""
    if rule_id.startswith("semgrep:"):
        # Strip provider prefix so sealevel rule ids match our seven canonical
        # ids when the YAML semgrep rule slug mirrors the canonical name.
        return rule_id.split(":", 1)[1]
    return rule_id


def _parse_location(location: str | None) -> int | None:
    if not isinstance(location, str):
        return None
    if ":" not in location:
        return None
    tail = location.rsplit(":", 1)[1]
    try:
        return int(tail)
    except ValueError:
        return None


def _classify(
    findings: list[dict[str, Any]],
    ground_truth: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (TP, FP, FN) lists."""
    tp: list[dict[str, Any]] = []
    fp: list[dict[str, Any]] = []
    fn: list[dict[str, Any]] = []

    matched_gt: set[int] = set()
    matched_findings: set[int] = set()

    for f_idx, f in enumerate(findings):
        f_rule = _normalize_rule_id(f.get("rule_id"))
        f_line = _parse_location(f.get("location"))
        for gt_idx, gt in enumerate(ground_truth):
            if gt_idx in matched_gt:
                continue
            gt_rule = _normalize_rule_id(gt.get("rule_id"))
            if f_rule != gt_rule or not gt_rule:
                continue
            gt_line = gt.get("approx_line")
            if f_line is None or not isinstance(gt_line, int):
                # Rule matches but we can't locate — still count as TP.
                matched_gt.add(gt_idx)
                matched_findings.add(f_idx)
                tp.append({"finding": f, "ground_truth": gt, "line_delta": None})
                break
            if abs(f_line - gt_line) <= LINE_TOLERANCE:
                matched_gt.add(gt_idx)
                matched_findings.add(f_idx)
                tp.append({
                    "finding": f,
                    "ground_truth": gt,
                    "line_delta": abs(f_line - gt_line),
                })
                break

    for f_idx, f in enumerate(findings):
        if f_idx not in matched_findings:
            fp.append({"finding": f})

    for gt_idx, gt in enumerate(ground_truth):
        if gt_idx not in matched_gt:
            fn.append({"ground_truth": gt})

    return tp, fp, fn


def _finding_rows_from_bundle(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    scan_result = bundle.get("scan_result") or {}
    out: list[dict[str, Any]] = []
    for f in scan_result.get("findings", []):
        out.append({
            "rule_id": f.get("rule_id"),
            "severity": f.get("severity"),
            "location": f.get("location"),
            "title": f.get("title"),
            "confidence": f.get("confidence"),
            "description": (f.get("description") or "")[:400],
        })
    return out


async def _run_one(
    fx: dict[str, Any],
    fixtures_root: Path,
    output_root: Path,
    force_degraded: bool,
    per_fixture_timeout: float,
    sem: asyncio.Semaphore,
    log_path: Path,
) -> FixtureResult:
    name = fx["name"]
    rel = fx["path"]
    fixture_path = (fixtures_root / rel).resolve()
    scale = fx["scale"]
    has_vuln = bool(fx["has_vuln"])
    ground_truth = fx.get("ground_truth") or []

    async with sem:
        start = time.perf_counter()
        _append_log(log_path, f"[start] {name} ({rel}) scale={scale}")
        try:
            # run_audit is sync + CPU/IO-bound (LLM call inside). Run it in
            # a thread so asyncio.gather actually fans out in parallel.
            bundle = await asyncio.wait_for(
                asyncio.to_thread(
                    run_audit,
                    fixture_path,
                    output_root / "audits",
                    name,
                    force_degraded,
                    False,
                ),
                timeout=per_fixture_timeout,
            )
        except asyncio.TimeoutError:
            duration = time.perf_counter() - start
            _append_log(log_path, f"[timeout] {name} after {duration:.1f}s")
            return FixtureResult(
                name=name,
                path=rel,
                scale=scale,
                has_vuln=has_vuln,
                duration_s=duration,
                decision="timeout",
                findings=[],
                fn=[{"ground_truth": gt} for gt in ground_truth],
                error=f"per-fixture timeout after {per_fixture_timeout:.1f}s",
            )
        except Exception as exc:  # noqa: BLE001
            duration = time.perf_counter() - start
            tb = traceback.format_exc(limit=4)
            _append_log(log_path, f"[error] {name}: {exc}\n{tb}")
            return FixtureResult(
                name=name,
                path=rel,
                scale=scale,
                has_vuln=has_vuln,
                duration_s=duration,
                decision="error",
                findings=[],
                fn=[{"ground_truth": gt} for gt in ground_truth],
                error=f"{type(exc).__name__}: {exc}",
            )

        duration = time.perf_counter() - start
        findings = _finding_rows_from_bundle(bundle)
        decision = (bundle.get("scan_result") or {}).get("decision", "unknown")
        tp, fp, fn = _classify(findings, ground_truth)
        _append_log(
            log_path,
            f"[done]  {name} t={duration:.1f}s decision={decision} "
            f"findings={len(findings)} TP={len(tp)} FP={len(fp)} FN={len(fn)}",
        )
        return FixtureResult(
            name=name,
            path=rel,
            scale=scale,
            has_vuln=has_vuln,
            duration_s=duration,
            decision=decision,
            findings=findings,
            tp=tp,
            fp=fp,
            fn=fn,
        )


def _append_log(log_path: Path, msg: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def _aggregate(results: list[FixtureResult]) -> dict[str, Any]:
    def f1(p: float, r: float) -> float:
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)

    def pack(subset: list[FixtureResult]) -> dict[str, Any]:
        total_tp = sum(len(r.tp) for r in subset)
        total_fp = sum(len(r.fp) for r in subset)
        total_fn = sum(len(r.fn) for r in subset)
        precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 1.0
        recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 1.0
        durations = [r.duration_s for r in subset if r.duration_s > 0]
        return {
            "fixture_count": len(subset),
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1(precision, recall), 4),
            "avg_duration_s": round(sum(durations) / len(durations), 2) if durations else 0.0,
            "max_duration_s": round(max(durations), 2) if durations else 0.0,
            "min_duration_s": round(min(durations), 2) if durations else 0.0,
        }

    by_scale = {
        "small": pack([r for r in results if r.scale == "small"]),
        "medium": pack([r for r in results if r.scale == "medium"]),
        "large": pack([r for r in results if r.scale == "large"]),
    }
    overall = pack(results)
    degraded_count = sum(1 for r in results if r.decision == "degraded")
    error_count = sum(1 for r in results if r.decision in ("error", "timeout"))
    return {
        "overall": overall,
        "per_scale": by_scale,
        "degraded_count": degraded_count,
        "error_count": error_count,
    }


def _render_markdown(
    summary: dict[str, Any],
    results: list[FixtureResult],
    tag: str,
    benchmark_sha: str,
) -> str:
    lines = [
        f"# Phase 6 Benchmark Summary — `{tag}`",
        "",
        f"- benchmark.yaml sha256: `{benchmark_sha[:16]}…`",
        f"- fixtures: {summary['overall']['fixture_count']}",
        f"- degraded runs: {summary['degraded_count']}",
        f"- errored runs: {summary['error_count']}",
        "",
        "## Aggregate",
        "",
        "| Scope | Fixtures | TP | FP | FN | Precision | Recall | F1 | Avg Dur(s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    o = summary["overall"]
    lines.append(
        f"| overall | {o['fixture_count']} | {o['tp']} | {o['fp']} | {o['fn']} "
        f"| {o['precision']} | {o['recall']} | {o['f1']} | {o['avg_duration_s']} |"
    )
    for scale in ("small", "medium", "large"):
        s = summary["per_scale"][scale]
        lines.append(
            f"| {scale} | {s['fixture_count']} | {s['tp']} | {s['fp']} | {s['fn']} "
            f"| {s['precision']} | {s['recall']} | {s['f1']} | {s['avg_duration_s']} |"
        )

    lines.extend(["", "## Per-fixture", "", "| Fixture | Scale | Decision | TP | FP | FN | Dur(s) |",
                  "|---|---|---|---|---|---|---|"])
    for r in sorted(results, key=lambda x: x.name):
        lines.append(
            f"| `{r.name}` | {r.scale} | {r.decision} "
            f"| {len(r.tp)} | {len(r.fp)} | {len(r.fn)} | {r.duration_s:.1f} |"
        )
    lines.append("")
    return "\n".join(lines)


async def _main(args: argparse.Namespace) -> int:
    benchmark_path = Path(args.benchmark).resolve()
    if not benchmark_path.exists():
        print(f"error: benchmark.yaml not found: {benchmark_path}", file=sys.stderr)
        return 2

    raw = benchmark_path.read_bytes()
    bench_sha = hashlib.sha256(raw).hexdigest()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        print(f"error: invalid YAML: {exc}", file=sys.stderr)
        return 2

    fixtures = data.get("fixtures") or []
    if args.only:
        only_set = set(args.only.split(","))
        fixtures = [fx for fx in fixtures if fx.get("name") in only_set]
        if not fixtures:
            print(f"error: --only matched 0 fixtures: {args.only}", file=sys.stderr)
            return 2

    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "per-fixture").mkdir(exist_ok=True)
    log_path = output_root / "run.log"
    if log_path.exists():
        log_path.unlink()

    fixtures_root = benchmark_path.parent
    sem = asyncio.Semaphore(args.concurrency)

    t0 = time.perf_counter()
    tasks = [
        _run_one(
            fx,
            fixtures_root,
            output_root,
            args.degraded,
            args.per_fixture_timeout,
            sem,
            log_path,
        )
        for fx in fixtures
    ]
    results: list[FixtureResult] = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - t0

    # Persist per-fixture
    for r in results:
        (output_root / "per-fixture" / f"{r.name}.json").write_text(
            json.dumps(r.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    summary = _aggregate(results)
    summary["tag"] = args.tag
    summary["benchmark_sha256"] = bench_sha
    summary["concurrency"] = args.concurrency
    summary["wall_clock_s"] = round(elapsed, 2)
    summary["force_degraded"] = args.degraded

    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_root / "summary.md").write_text(
        _render_markdown(summary, results, args.tag, bench_sha), encoding="utf-8"
    )

    o = summary["overall"]
    print(
        f"[run_benchmark] tag={args.tag} fixtures={o['fixture_count']} "
        f"precision={o['precision']} recall={o['recall']} f1={o['f1']} "
        f"avg_dur={o['avg_duration_s']}s wall={elapsed:.1f}s "
        f"degraded={summary['degraded_count']} errors={summary['error_count']}"
    )
    print(f"[run_benchmark] output -> {output_root}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__ or "")
    p.add_argument(
        "--benchmark",
        default=str(_SKILL_ROOT.parent.parent / "test-fixtures" / "benchmark.yaml"),
        help="Path to benchmark.yaml",
    )
    p.add_argument("--output", required=True, help="Output directory")
    p.add_argument("--tag", default="baseline", help="Run tag (embedded in summary)")
    p.add_argument("--concurrency", type=int, default=5, help="Max parallel fixtures")
    p.add_argument(
        "--per-fixture-timeout",
        type=float,
        default=300.0,
        help="Seconds before a single fixture is aborted",
    )
    p.add_argument(
        "--only",
        default=None,
        help="Comma-separated fixture names to run (default: all)",
    )
    p.add_argument(
        "--degraded",
        action="store_true",
        help="Force degraded mode (skip LLM even if keys are present)",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
