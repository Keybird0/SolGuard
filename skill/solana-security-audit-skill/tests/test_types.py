"""Tests for core.types — basic round-trip + invariants."""

from __future__ import annotations

import pytest

from core.types import Finding, Severity, Statistics


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
    )


def test_severity_from_value_case_insensitive():
    assert Severity.from_value("HIGH") is Severity.HIGH
    assert Severity.from_value("critical") is Severity.CRITICAL

    with pytest.raises(ValueError):
        Severity.from_value("nope")


def test_finding_round_trip():
    f = make_finding()
    data = f.to_dict()
    assert data["severity"] == "High"
    restored = Finding.from_dict(data)
    assert restored == f


def test_statistics_from_findings():
    findings = [
        make_finding(Severity.CRITICAL, "C-1"),
        make_finding(Severity.HIGH, "H-1"),
        make_finding(Severity.HIGH, "H-2"),
        make_finding(Severity.INFO, "I-1"),
    ]
    stats = Statistics.from_findings(findings)
    assert stats.critical == 1
    assert stats.high == 2
    assert stats.info == 1
    assert stats.total == 4

    d = stats.to_dict()
    assert d["total"] == 4
    assert d["medium"] == 0
