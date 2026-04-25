#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Phase 6.4.1 · long-run stability (soak) harness.

Pre-wired for Phase 5's Layer-2 public deployment. Sends N audit
batches through the live `/api/audit` endpoint and tracks:

* end-to-end wall time per batch (submit -> completed)
* HTTP error rate (4xx / 5xx / network)
* pipeline error rate (task.status == 'failed')
* p50 / p95 latency

Deliberately ``httpx``-light so it can run on a minimal Python env.
Usage (once the online MVP is live — see P5.x):

    python scripts/soak_test.py \\
        --base-url https://solguard.xyz \\
        --runs 20 \\
        --concurrency 4 \\
        --free-audit \\
        --output outputs/phase6-soak.json

Exits non-zero when success rate < --min-success (default 0.95) so CI
can gate M4 on real live data. Until deployment lands this script is
intentionally unused; `python -m py_compile` + `--help` still have to
work (local sanity checks).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import httpx  # noqa: WPS433 -- optional, loaded lazily below
except ImportError:  # pragma: no cover -- env without httpx yet
    httpx = None  # type: ignore[assignment]

DEFAULT_TARGETS = [
    {"github": "https://github.com/solana-labs/example-helloworld"},
    {"github": "https://github.com/coral-xyz/anchor-example"},
    {"contractAddress": "Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS"},
]

TERMINAL = {"completed", "failed"}


@dataclass
class RunRecord:
    idx: int
    batch_id: str | None
    ok: bool
    error: str | None
    pipeline_failed: int
    elapsed_sec: float
    tasks: int


async def _submit_batch(
    client: "httpx.AsyncClient", base: str, email: str, targets: list[dict]
) -> dict:
    resp = await client.post(
        f"{base}/api/audit",
        json={"targets": targets, "email": email},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


async def _await_terminal(
    client: "httpx.AsyncClient",
    base: str,
    batch_id: str,
    timeout_sec: float,
) -> dict:
    deadline = time.monotonic() + timeout_sec
    last: dict = {}
    while time.monotonic() < deadline:
        resp = await client.get(
            f"{base}/api/audit/batch/{batch_id}", timeout=15.0
        )
        resp.raise_for_status()
        last = resp.json()
        tasks = last.get("tasks", [])
        if tasks and all(t.get("status") in TERMINAL for t in tasks):
            return last
        await asyncio.sleep(5.0)
    raise TimeoutError(f"batch {batch_id} did not reach terminal state in {timeout_sec}s")


async def _run_one(
    idx: int,
    client: "httpx.AsyncClient",
    base: str,
    email: str,
    targets: list[dict],
    timeout_sec: float,
) -> RunRecord:
    t0 = time.monotonic()
    try:
        submit = await _submit_batch(client, base, email, targets)
        batch_id = submit.get("batchId")
        if not batch_id:
            return RunRecord(idx, None, False, "no batchId in response", 0, 0.0, 0)
        final = await _await_terminal(client, base, batch_id, timeout_sec)
        tasks = final.get("tasks", [])
        failed = sum(1 for t in tasks if t.get("status") == "failed")
        elapsed = time.monotonic() - t0
        return RunRecord(
            idx=idx,
            batch_id=batch_id,
            ok=failed == 0,
            error=None if failed == 0 else f"{failed} task(s) failed",
            pipeline_failed=failed,
            elapsed_sec=round(elapsed, 2),
            tasks=len(tasks),
        )
    except Exception as exc:  # noqa: BLE001 — we want everything captured
        return RunRecord(
            idx=idx,
            batch_id=None,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            pipeline_failed=0,
            elapsed_sec=round(time.monotonic() - t0, 2),
            tasks=0,
        )


async def _main_async(args: argparse.Namespace) -> int:
    if httpx is None:
        print(
            "error: httpx is not installed. Install with `pip install httpx` "
            "before running the soak harness.",
            file=sys.stderr,
        )
        return 2

    random.seed(args.seed)
    base = args.base_url.rstrip("/")
    sem = asyncio.Semaphore(args.concurrency)

    async def _guarded(idx: int, client: httpx.AsyncClient) -> RunRecord:
        async with sem:
            targets = [random.choice(DEFAULT_TARGETS)]
            email = f"soak+{idx}-{int(time.time())}@solguard.local"
            return await _run_one(idx, client, base, email, targets, args.task_timeout)

    async with httpx.AsyncClient(http2=False) as client:
        records = await asyncio.gather(
            *(_guarded(i, client) for i in range(args.runs))
        )

    ok_count = sum(1 for r in records if r.ok)
    success_rate = ok_count / max(1, len(records))
    latencies = [r.elapsed_sec for r in records if r.elapsed_sec > 0]
    summary: dict[str, Any] = {
        "runs": len(records),
        "ok": ok_count,
        "success_rate": round(success_rate, 4),
        "p50_sec": round(statistics.median(latencies), 2) if latencies else 0.0,
        "p95_sec": round(
            statistics.quantiles(latencies, n=20)[18], 2
        ) if len(latencies) >= 20 else round(max(latencies or [0.0]), 2),
        "pipeline_failures": sum(r.pipeline_failed for r in records),
        "records": [asdict(r) for r in records],
        "base_url": base,
        "concurrency": args.concurrency,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(
        f"soak: {ok_count}/{len(records)} ok · "
        f"rate={success_rate:.2%} · p50={summary['p50_sec']}s · "
        f"p95={summary['p95_sec']}s → {out}",
    )
    return 0 if success_rate >= args.min_success else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--base-url",
        default=os.environ.get("SOLGUARD_BASE_URL", "http://localhost:3000"),
        help="Root of the SolGuard server (e.g. https://solguard.xyz)",
    )
    p.add_argument("--runs", type=int, default=20, help="How many batches to submit")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument(
        "--task-timeout",
        type=float,
        default=420.0,
        help="Per-batch timeout in seconds (default 7 min)",
    )
    p.add_argument(
        "--min-success",
        type=float,
        default=0.95,
        help="Fail hard when success rate falls below this (M4 gate = 0.95)",
    )
    p.add_argument(
        "--free-audit",
        action="store_true",
        help="Assume the server has FREE_AUDIT=true so no Phantom pay is needed",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--output",
        default="outputs/phase6-soak.json",
        help="Where to store the JSON summary",
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.free_audit:
        print(
            "warning: running without --free-audit will require a real "
            "Phantom signature per batch. Consider setting FREE_AUDIT=true "
            "on the server for soak runs.",
            file=sys.stderr,
        )
    try:
        return asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
