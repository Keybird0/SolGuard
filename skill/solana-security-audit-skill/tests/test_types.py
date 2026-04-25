"""Tests for core.types — serialization round-trips and invariants.

Covers every dataclass declared in :mod:`core.types` so the contract is
frozen against regression before downstream tools (P2.2.x parse, P2.3.x
scan, P2.5.x report, P3 backend) start consuming it.
"""

from __future__ import annotations

import pytest

from core.types import (
    AuthorityInfo,
    Callback,
    Finding,
    ParsedContract,
    ReportBundle,
    ScanResult,
    ScanTask,
    Severity,
    Statistics,
    TaskStatus,
    TokenExtension,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_finding(sev: Severity = Severity.HIGH, fid: str = "F-001") -> Finding:
    return Finding(
        id=fid,
        severity=sev,
        title="Missing Signer Check",
        location="lib.rs:42",
        description="Account is not verified as signer.",
        impact="Unauthorized execution possible.",
        recommendation="Use Signer<'info> type.",
        rule_id="missing_signer_check",
        confidence=0.9,
        kill_signal={"answered": True, "verdict": "valid"},
    )


def make_authority() -> AuthorityInfo:
    return AuthorityInfo(
        mint_authority=None,
        freeze_authority=None,
        update_authority="UpdAuth1111111111111111111111111111111111",
        program_upgrade_authority=None,
        extensions=[
            TokenExtension(
                name="PermanentDelegate",
                params={"delegate": "Del1111111111111111111111111111111111111"},
                red_flag=True,
                severity_hint=Severity.CRITICAL,
            ),
            TokenExtension(
                name="TransferFee",
                params={"rate_bps": 25, "max": 1_000_000},
                red_flag=False,
            ),
        ],
    )


def make_reports() -> ReportBundle:
    return ReportBundle(
        risk_summary="outputs/t1/risk_summary.md",
        assessment="outputs/t1/assessment.md",
        checklist="outputs/t1/checklist.md",
        report_json="outputs/t1/report.json",
        sha256={"risk_summary": "a" * 64, "assessment": "b" * 64},
        bytes={"risk_summary": 1234, "assessment": 4321},
    )


def make_scan_result(
    *,
    source_visibility: str = "source",
    decision: str = "proceed",
    with_authority: bool = True,
) -> ScanResult:
    findings = [
        make_finding(Severity.CRITICAL, "C-1"),
        make_finding(Severity.HIGH, "H-1"),
    ]
    return ScanResult(
        contract_name="counter",
        contract_path="contracts/counter/src/lib.rs",
        risk_level="B",
        findings=findings,
        statistics=Statistics.from_findings(findings),
        timestamp="2026-04-22T10:00:00+00:00",
        authority=make_authority() if with_authority else None,
        inputs_summary="GitHub repo + mint 2Cd...Eyq",
        source_visibility=source_visibility,  # type: ignore[arg-type]
        decision=decision,  # type: ignore[arg-type]
        reports=make_reports(),
        callback=Callback(url="https://cb.example/solguard", status="sent", attempts=1, last_http_status=200),
    )


# ---------------------------------------------------------------------------
# Enum round-trips
# ---------------------------------------------------------------------------


def test_severity_from_value_case_insensitive() -> None:
    assert Severity.from_value("HIGH") is Severity.HIGH
    assert Severity.from_value("critical") is Severity.CRITICAL

    with pytest.raises(ValueError):
        Severity.from_value("nope")


def test_task_status_from_value() -> None:
    assert TaskStatus.from_value("pending") is TaskStatus.PENDING
    assert TaskStatus.from_value("completed") is TaskStatus.COMPLETED
    with pytest.raises(ValueError):
        TaskStatus.from_value("unknown")


# ---------------------------------------------------------------------------
# Finding / Statistics
# ---------------------------------------------------------------------------


def test_finding_round_trip() -> None:
    f = make_finding()
    data = f.to_dict()
    assert data["severity"] == "High"
    assert data["kill_signal"] == {"answered": True, "verdict": "valid"}
    restored = Finding.from_dict(data)
    assert restored == f


def test_finding_from_dict_invalid_severity() -> None:
    bad = make_finding().to_dict()
    bad["severity"] = "Galactic"
    with pytest.raises(ValueError):
        Finding.from_dict(bad)


def test_statistics_from_findings() -> None:
    findings = [
        make_finding(Severity.CRITICAL, "C-1"),
        make_finding(Severity.HIGH, "H-1"),
        make_finding(Severity.HIGH, "H-2"),
        make_finding(Severity.INFO, "I-1"),
    ]
    stats = Statistics.from_findings(findings)
    assert (stats.critical, stats.high, stats.medium, stats.low, stats.info) == (
        1,
        2,
        0,
        0,
        1,
    )
    assert stats.total == 4


def test_statistics_from_dict_round_trip() -> None:
    stats = Statistics(critical=1, high=2, medium=3, low=4, info=5)
    data = stats.to_dict()
    assert data["total"] == 15
    restored = Statistics.from_dict(data)
    assert restored == stats


# ---------------------------------------------------------------------------
# Parsed / Authority / Extension / Callback / Reports
# ---------------------------------------------------------------------------


def test_parsed_contract_round_trip() -> None:
    pc = ParsedContract(
        file_path="src/lib.rs",
        source_code="pub fn foo() {}",
        functions=[{"name": "foo", "line": 1}],
        accounts=[{"name": "Vault", "fields": [{"name": "authority", "ty": "Signer"}]}],
        instructions=[{"name": "deposit"}],
        anchor_attrs=[{"target": "Vault.authority", "attr": "signer"}],
        metadata={"anchor_version": "0.29.0"},
        parse_error=None,
    )
    restored = ParsedContract.from_dict(pc.to_dict())
    assert restored == pc


def test_token_extension_red_flag() -> None:
    ext = TokenExtension(
        name="PermanentDelegate",
        params={"delegate": "Del1"},
        red_flag=True,
        severity_hint=Severity.CRITICAL,
    )
    data = ext.to_dict()
    assert data["red_flag"] is True
    assert data["severity_hint"] == "Critical"
    restored = TokenExtension.from_dict(data)
    assert restored == ext


def test_authority_info_round_trip() -> None:
    auth = make_authority()
    restored = AuthorityInfo.from_dict(auth.to_dict())
    assert restored == auth
    assert len(restored.extensions) == 2
    assert restored.extensions[0].red_flag is True


def test_callback_invalid_status_raises() -> None:
    with pytest.raises(ValueError):
        Callback.from_dict({"url": None, "status": "exploded", "attempts": 0})


def test_report_bundle_round_trip() -> None:
    rb = make_reports()
    restored = ReportBundle.from_dict(rb.to_dict())
    assert restored == rb


# ---------------------------------------------------------------------------
# ScanResult / ScanTask
# ---------------------------------------------------------------------------


def test_scan_result_round_trip_with_authority() -> None:
    sr = make_scan_result()
    data = sr.to_dict()
    assert data["authority"] is not None
    assert data["source_visibility"] == "source"
    assert data["reports"]["risk_summary"].endswith("risk_summary.md")
    restored = ScanResult.from_dict(data)
    assert restored == sr


def test_scan_result_degraded_mode() -> None:
    sr = make_scan_result(
        source_visibility="bytecode_only",
        decision="degraded",
        with_authority=True,
    )
    data = sr.to_dict()
    assert data["source_visibility"] == "bytecode_only"
    assert data["decision"] == "degraded"
    restored = ScanResult.from_dict(data)
    assert restored.source_visibility == "bytecode_only"
    assert restored.decision == "degraded"


def test_scan_result_invalid_decision_raises() -> None:
    sr = make_scan_result()
    data = sr.to_dict()
    data["decision"] = "launch_nukes"
    with pytest.raises(ValueError):
        ScanResult.from_dict(data)


def test_scan_task_round_trip_with_result() -> None:
    task = ScanTask(
        task_id="tsk_0001",
        status=TaskStatus.COMPLETED,
        progress="7/7",
        result=make_scan_result(),
        error=None,
        created_at="2026-04-22T09:00:00+00:00",
        completed_at="2026-04-22T09:04:30+00:00",
    )
    data = task.to_dict()
    assert data["status"] == "completed"
    assert data["result"]["contract_name"] == "counter"
    restored = ScanTask.from_dict(data)
    assert restored == task


def test_scan_task_empty_result() -> None:
    task = ScanTask(task_id="tsk_empty", status=TaskStatus.PENDING)
    data = task.to_dict()
    assert data["result"] is None
    restored = ScanTask.from_dict(data)
    assert restored.result is None
    assert restored.status is TaskStatus.PENDING
