#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""cProfile wrapper around ``run_audit.run_audit`` for Phase 6.3.1.

Runs the pipeline against a single fixture (or a comma-separated list)
and emits both a ``.prof`` file (consumable by ``snakeviz``) and a
condensed top-N text dump.

Usage::

    uv run python scripts/profile_audit.py \
        --fixture ../../test-fixtures/real-world/large/rw11_amm_slice.rs \
        --output-dir ../../outputs/phase6-profile \
        --force-degraded   # recommended — removes LLM latency noise

``--force-degraded`` should be used for local CPU profiling so the
cProfile totals aren't dominated by HTTP wait time (which is not a
real optimization target for the skill side). For wall-clock
measurements use ``run_benchmark.py`` instead.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

_THIS = Path(__file__).resolve()
_SKILL_ROOT = _THIS.parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from scripts.run_audit import run_audit  # noqa: E402


def _profile_one(
    fixture: Path,
    output_dir: Path,
    force_degraded: bool,
    top_n: int,
) -> dict[str, float]:
    task_id = fixture.stem
    prof_path = output_dir / f"{task_id}.prof"
    text_path = output_dir / f"{task_id}.txt"
    output_dir.mkdir(parents=True, exist_ok=True)

    pr = cProfile.Profile()
    pr.enable()
    t0 = time.perf_counter()
    run_audit(
        fixture_path=fixture,
        output_root=output_dir / "audits",
        task_id=task_id,
        force_degraded=force_degraded,
        emit_events=False,
    )
    elapsed = time.perf_counter() - t0
    pr.disable()
    pr.dump_stats(str(prof_path))

    buf = io.StringIO()
    stats = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    print(f"=== {task_id}  wall={elapsed:.2f}s  (degraded={force_degraded}) ===",
          file=buf)
    stats.print_stats(top_n)
    print("--- sorted by tottime ---", file=buf)
    stats.sort_stats("tottime").print_stats(top_n)
    text_path.write_text(buf.getvalue(), encoding="utf-8")
    print(f"[profile] {task_id}: wall={elapsed:.2f}s  -> {prof_path.name}")
    return {"fixture": task_id, "elapsed_s": elapsed}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__ or "")
    p.add_argument(
        "--fixture",
        required=True,
        help="Path to a single fixture .rs file or comma-separated list",
    )
    p.add_argument("--output-dir", required=True, help="Where to write .prof / .txt")
    p.add_argument(
        "--top-n",
        type=int,
        default=40,
        help="Rows to include in the text dump per sort order",
    )
    p.add_argument(
        "--force-degraded",
        action="store_true",
        help="Skip LLM (strongly recommended for deterministic profiling)",
    )
    args = p.parse_args()

    fixtures = [Path(x.strip()).resolve() for x in args.fixture.split(",") if x.strip()]
    output_dir = Path(args.output_dir).resolve()
    stats_summary: list[dict[str, float]] = []
    for fx in fixtures:
        if not fx.is_file():
            print(f"error: fixture not found: {fx}", file=sys.stderr)
            return 2
        stats_summary.append(_profile_one(fx, output_dir, args.force_degraded, args.top_n))

    print("\n== summary ==")
    for s in stats_summary:
        print(f"  {s['fixture']:32s} {s['elapsed_s']:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
