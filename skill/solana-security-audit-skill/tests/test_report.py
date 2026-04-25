# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""P2.5.1 — Report persistence tests.

Covers the four non-negotiable guarantees:

1. All four artefacts (3 × Markdown + 1 × JSON) land on disk with matching
   SHA-256 + byte sizes.
2. ``report.json`` round-trips through :meth:`ScanResult.from_dict`.
3. Callback semantics — ``None`` → ``skipped``; HTTP 500 → ``failed``
   without raising.
4. Degenerate inputs (empty Markdown dict, concurrent task ids) don't
   corrupt the output tree.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest

from core.types import ScanResult, Statistics
from tools.solana_report import persist


def _baseline_scan_result(path: str = "fixture.rs") -> ScanResult:
    return ScanResult(
        contract_name="fixture",
        contract_path=path,
        risk_level="High",
        findings=[],
        statistics=Statistics(high=1),
    )


def _sample_markdown() -> dict[str, str]:
    return {
        "risk_summary": "# Risk Summary\n\nSeverity: High.\n",
        "assessment": "# Assessment\n\nDetailed findings here.\n",
        "checklist": "# Checklist\n\n- [ ] review missing_signer\n",
    }


# ---------------------------------------------------------------------------
# 1. Files written + SHA-256 round-trips (2 cases)
# ---------------------------------------------------------------------------


def test_persist_writes_three_markdown_and_report_json(tmp_path: Path) -> None:
    result = persist(
        task_id="task-001",
        scan_result=_baseline_scan_result(),
        ai_markdown=_sample_markdown(),
        output_root=tmp_path,
    )
    out_dir = Path(result["output_dir"])
    assert (out_dir / "risk_summary.md").exists()
    assert (out_dir / "assessment.md").exists()
    assert (out_dir / "checklist.md").exists()
    assert (out_dir / "report.json").exists()


def test_persist_sha256_matches_on_disk_bytes(tmp_path: Path) -> None:
    md = _sample_markdown()
    result = persist(
        task_id="task-002",
        scan_result=_baseline_scan_result(),
        ai_markdown=md,
        output_root=tmp_path,
    )
    sha = result["report"]["sha256"]
    sizes = result["report"]["bytes"]
    out_dir = Path(result["output_dir"])
    for key in ("risk_summary", "assessment", "checklist"):
        raw = (out_dir / f"{key}.md").read_bytes()
        assert sha[key] == hashlib.sha256(raw).hexdigest()
        assert sizes[key] == len(raw)
    raw_json = (out_dir / "report.json").read_bytes()
    assert sha["report_json"] == hashlib.sha256(raw_json).hexdigest()
    assert sizes["report_json"] == len(raw_json)


# ---------------------------------------------------------------------------
# 2. report.json round-trips through ScanResult (1 case)
# ---------------------------------------------------------------------------


def test_persist_report_json_round_trips_through_scan_result(tmp_path: Path) -> None:
    result = persist(
        task_id="task-003",
        scan_result=_baseline_scan_result(),
        ai_markdown=_sample_markdown(),
        output_root=tmp_path,
    )
    report_json_path = Path(result["output_dir"]) / "report.json"
    data = json.loads(report_json_path.read_text(encoding="utf-8"))
    restored = ScanResult.from_dict(data)
    assert restored.contract_name == "fixture"
    assert restored.statistics.high == 1
    assert restored.reports is not None
    assert restored.callback is not None
    assert restored.callback.status == "skipped"


# ---------------------------------------------------------------------------
# 3. Callback semantics (2 cases)
# ---------------------------------------------------------------------------


def test_persist_no_callback_url_yields_skipped(tmp_path: Path) -> None:
    result = persist(
        task_id="task-004",
        scan_result=_baseline_scan_result(),
        ai_markdown=_sample_markdown(),
        output_root=tmp_path,
        callback_url=None,
    )
    assert result["callback"]["status"] == "skipped"
    assert result["callback"]["attempts"] == 0


def test_persist_webhook_http_error_marks_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _FakeResponse:
        status_code = 500

    def _fake_post(url: str, json: Any = None, timeout: int = 30) -> _FakeResponse:
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", _fake_post)
    result = persist(
        task_id="task-005",
        scan_result=_baseline_scan_result(),
        ai_markdown=_sample_markdown(),
        output_root=tmp_path,
        callback_url="https://example.invalid/hook",
    )
    assert result["callback"]["status"] == "failed"
    assert result["callback"]["last_http_status"] == 500
    assert result["callback"]["attempts"] == 1


def test_persist_webhook_exception_marks_failed_without_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise httpx.TimeoutException("network down")

    monkeypatch.setattr(httpx, "post", _raise)
    result = persist(
        task_id="task-006",
        scan_result=_baseline_scan_result(),
        ai_markdown=_sample_markdown(),
        output_root=tmp_path,
        callback_url="https://example.invalid/hook",
    )
    assert result["callback"]["status"] == "failed"
    assert result["callback"]["last_http_status"] is None


# ---------------------------------------------------------------------------
# 4. Degenerate inputs + concurrency (2 cases)
# ---------------------------------------------------------------------------


def test_persist_empty_markdown_dict_still_writes_stubs(tmp_path: Path) -> None:
    result = persist(
        task_id="task-007",
        scan_result=_baseline_scan_result(),
        ai_markdown={},
        output_root=tmp_path,
    )
    out_dir = Path(result["output_dir"])
    for key in ("risk_summary", "assessment", "checklist"):
        assert (out_dir / f"{key}.md").read_text(encoding="utf-8") == ""
        assert result["report"]["sha256"][key] == hashlib.sha256(b"").hexdigest()
        assert result["report"]["bytes"][key] == 0


def test_persist_concurrent_task_ids_do_not_cross_contaminate(
    tmp_path: Path,
) -> None:
    def _run(task_id: str) -> dict[str, Any]:
        md = _sample_markdown()
        md["risk_summary"] = f"# Risk for {task_id}\n"
        return persist(
            task_id=task_id,
            scan_result=_baseline_scan_result(path=f"{task_id}.rs"),
            ai_markdown=md,
            output_root=tmp_path,
        )

    task_ids = [f"task-concurrent-{i:02d}" for i in range(5)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_run, task_ids))
    for tid, result in zip(task_ids, results, strict=True):
        out_dir = Path(result["output_dir"])
        assert out_dir.name == tid
        text = (out_dir / "risk_summary.md").read_text(encoding="utf-8")
        assert tid in text
        data = json.loads((out_dir / "report.json").read_text("utf-8"))
        assert data["contract_path"] == f"{tid}.rs"


def test_persist_rejects_empty_task_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        persist(
            task_id="",
            scan_result=_baseline_scan_result(),
            ai_markdown=_sample_markdown(),
            output_root=tmp_path,
        )
