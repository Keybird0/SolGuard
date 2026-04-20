"""solana_report tool — emit 3-tier Markdown + JSON bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.types import Finding, ScanResult, Severity, Statistics
from reporters.markdown import render_assessment, render_checklist, render_risk_summary


def build_scan_result(
    contract_name: str,
    contract_path: str,
    findings_data: list[dict[str, Any]],
    risk_level: str | None = None,
) -> ScanResult:
    findings = [Finding.from_dict(f) for f in findings_data]
    stats = Statistics.from_findings(findings)
    risk = risk_level or _derive_risk_level(stats)
    return ScanResult(
        contract_name=contract_name,
        contract_path=contract_path,
        risk_level=risk,
        findings=findings,
        statistics=stats,
    )


def emit(result: ScanResult, output_dir: Path | str) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    summary_path = out / "risk_summary.md"
    assessment_path = out / "assessment.md"
    checklist_path = out / "checklist.md"
    json_path = out / "report.json"

    summary_path.write_text(render_risk_summary(result), encoding="utf-8")
    assessment_path.write_text(render_assessment(result), encoding="utf-8")
    checklist_path.write_text(render_checklist(result), encoding="utf-8")
    json_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    return {
        "risk_summary_md": str(summary_path),
        "assessment_md": str(assessment_path),
        "checklist_md": str(checklist_path),
        "report_json": str(json_path),
    }


def _derive_risk_level(stats: Statistics) -> str:
    if stats.critical > 0:
        return "D"
    if stats.high > 0:
        return "C"
    if stats.medium > 0:
        return "B"
    if stats.low > 0:
        return "A"
    return "S"


def execute(
    contract_name: str,
    contract_path: str,
    findings: list[dict[str, Any]],
    output_dir: str = "./outputs",
    risk_level: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness Tool entry point."""
    result = build_scan_result(contract_name, contract_path, findings, risk_level)
    paths = emit(result, Path(output_dir))
    # Surface enum values as strings for JSON consumers.
    for f in result.findings:
        if isinstance(f.severity, Severity):
            pass
    return {"paths": paths, "result": result.to_dict()}
