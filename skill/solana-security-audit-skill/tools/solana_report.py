# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""solana_report tool — persistence + integrity + optional webhook.

The AI-first pipeline asks the model to produce three Markdown sections
(``risk_summary``, ``assessment``, ``checklist``). This tool is responsible
for a **narrow, side-effect-only** job:

1. Persist the three Markdown files to ``<output_root>/<task_id>/*.md``.
2. Write ``report.json`` (the full :class:`core.types.ScanResult` structure)
   alongside them so machine consumers don't have to re-parse Markdown.
3. Hash every on-disk artefact with SHA-256 and record byte sizes.
4. Optionally POST the ``ReportBundle`` to ``callback_url`` (with fault
   tolerance — a 500 or timeout never raises).

No Markdown is generated here. Callers supply the already-rendered strings.
This keeps the Python code Markdown-template-free so format changes stay in
``references/report-templates.md`` + the AI prompts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from core.types import Callback, ReportBundle, ScanResult

__all__ = [
    "SolanaReportTool",
    "execute",
    "persist",
]


_SECTION_KEYS: tuple[str, ...] = ("risk_summary", "assessment", "checklist")


def _hash_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _coerce_scan_result(value: ScanResult | dict[str, Any]) -> ScanResult:
    if isinstance(value, ScanResult):
        return value
    return ScanResult.from_dict(value)


def _deliver_webhook(
    url: str,
    payload: dict[str, Any],
    timeout: int,
) -> Callback:
    cb = Callback(url=url, status="pending", attempts=1)
    try:
        response = httpx.post(url, json=payload, timeout=timeout)
        cb.last_http_status = response.status_code
        cb.status = "sent" if 200 <= response.status_code < 300 else "failed"
    except Exception:  # noqa: BLE001 — webhook failures must never raise
        cb.status = "failed"
    return cb


def persist(
    task_id: str,
    scan_result: ScanResult | dict[str, Any],
    ai_markdown: dict[str, str] | None = None,
    output_root: str | Path = "outputs",
    callback_url: str | None = None,
    webhook_timeout: int = 30,
) -> dict[str, Any]:
    """Write the three-tier reports + ``report.json`` and return the bundle.

    ``ai_markdown`` may omit keys; missing sections are written as an empty
    file so downstream consumers can still checksum them deterministically.
    """
    if not task_id or not isinstance(task_id, str):
        raise ValueError("task_id must be a non-empty string")

    markdown = dict(ai_markdown or {})
    sr = _coerce_scan_result(scan_result)

    out_dir = Path(output_root) / task_id
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = ReportBundle()
    sha: dict[str, str] = {}
    byte_sizes: dict[str, int] = {}

    # 1) Markdown sections ----------------------------------------------------
    for key in _SECTION_KEYS:
        path = out_dir / f"{key}.md"
        content = str(markdown.get(key, ""))
        raw = content.encode("utf-8")
        path.write_text(content, encoding="utf-8")
        setattr(bundle, key, str(path))
        sha[key] = _hash_bytes(raw)
        byte_sizes[key] = len(raw)

    # 2) report.json ----------------------------------------------------------
    # The ReportBundle and callback aren't known yet — fill them after the
    # file is written, with the same dict round-tripped back.
    sr.reports = bundle
    report_json_path = out_dir / "report.json"
    sr_dict = sr.to_dict()
    serialized = json.dumps(sr_dict, ensure_ascii=False, indent=2, default=str)
    raw_json = serialized.encode("utf-8")
    report_json_path.write_text(serialized, encoding="utf-8")
    bundle.report_json = str(report_json_path)
    sha["report_json"] = _hash_bytes(raw_json)
    byte_sizes["report_json"] = len(raw_json)

    bundle.sha256 = sha
    bundle.bytes = byte_sizes

    # 3) Optional webhook ----------------------------------------------------
    if callback_url:
        cb = _deliver_webhook(
            callback_url,
            {
                "task_id": task_id,
                "report": bundle.to_dict(),
                "scan_result": sr_dict,
            },
            timeout=webhook_timeout,
        )
    else:
        cb = Callback(url=None, status="skipped", attempts=0)

    sr.callback = cb
    sr.reports = bundle

    # Re-serialize report.json so callback + bundle metadata are embedded.
    final_dict = sr.to_dict()
    final_serialized = json.dumps(final_dict, ensure_ascii=False, indent=2, default=str)
    report_json_path.write_text(final_serialized, encoding="utf-8")
    sha["report_json"] = _hash_bytes(final_serialized.encode("utf-8"))
    byte_sizes["report_json"] = len(final_serialized.encode("utf-8"))
    bundle.sha256 = sha
    bundle.bytes = byte_sizes

    return {
        "task_id": task_id,
        "output_dir": str(out_dir),
        "report": bundle.to_dict(),
        "callback": cb.to_dict(),
        "scan_result": sr.to_dict(),
    }


def execute(
    task_id: str | None = None,
    scan_result: ScanResult | dict[str, Any] | None = None,
    ai_markdown: dict[str, str] | None = None,
    output_root: str | Path = "outputs",
    callback_url: str | None = None,
    webhook_timeout: int = 30,
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness tool entry point. Validates required args + delegates."""
    if task_id is None:
        raise ValueError("'task_id' argument is required")
    if scan_result is None:
        raise ValueError("'scan_result' argument is required")
    return persist(
        task_id=task_id,
        scan_result=scan_result,
        ai_markdown=ai_markdown,
        output_root=output_root,
        callback_url=callback_url,
        webhook_timeout=webhook_timeout,
    )


class SolanaReportTool:
    """OpenHarness Tool wrapper — thin delegate to :func:`persist`."""

    name: str = "solana_report"
    version: str = "v0.1.0"

    def execute(
        self,
        task_id: str | None = None,
        scan_result: ScanResult | dict[str, Any] | None = None,
        ai_markdown: dict[str, str] | None = None,
        output_root: str | Path = "outputs",
        callback_url: str | None = None,
        webhook_timeout: int = 30,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return execute(
            task_id=task_id,
            scan_result=scan_result,
            ai_markdown=ai_markdown,
            output_root=output_root,
            callback_url=callback_url,
            webhook_timeout=webhook_timeout,
            **kwargs,
        )
