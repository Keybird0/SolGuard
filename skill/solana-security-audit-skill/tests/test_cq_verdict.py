# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Unit tests for Gate-2 deterministic landing (``solana_cq_verdict``).

The LLM prompt side of Gate-2 now lives in
``references/l4-judge-playbook.md §2``; the Python code only applies the
action table (Q1/Q5 → KILL, others → DOWNGRADE with per-rule severity
floor, otherwise KEEP). These tests drive the action table directly with
synthesised ``verdict`` dicts.
"""

from __future__ import annotations

from typing import Any

from ai.agents.types import Candidate
from ai.judge.counter_question import apply_verdict
from core.types import Severity
from tools.solana_cq_verdict import execute as cq_execute


def _cand(
    *,
    rule_id: str = "missing_signer_check",
    severity: Severity = Severity.HIGH,
    source: str = "A2",
) -> Candidate:
    return Candidate(
        rule_id=rule_id,
        location="lib.rs:14",
        function_name="log_message",
        severity=severity,
        title=rule_id.replace("_", " ").title(),
        reason="stub",
        recommendation="stub",
        code_snippet=None,
        source=source,  # type: ignore[arg-type]
    )


_PATTERN_SIGNER: dict[str, Any] = {
    "id": "missing_signer_check",
    "severity": "High",
}

_PATTERN_SYSVAR: dict[str, Any] = {
    "id": "sysvar_spoofing",
    "severity": "Medium",
}


# ---------------------------------------------------------------------------
# KILL path — Q1 / Q5 any-YES must terminate the candidate.
# ---------------------------------------------------------------------------


def test_q1_yes_kills_candidate() -> None:
    cand = _cand()
    verdict = {
        "answers": [
            {"id": "q1_upstream_check", "yes": True, "evidence": "require_keys_eq!"},
            {"id": "q2_intended_behavior", "yes": False, "evidence": ""},
            {"id": "q3_admin_only", "yes": False, "evidence": ""},
            {"id": "q4_economic", "yes": False, "evidence": ""},
            {"id": "q5_ack_by_prior_audit", "yes": False, "evidence": ""},
            {"id": "q6_public_data", "yes": False, "evidence": ""},
        ],
        "verdict": "kill",
        "summary": "upstream authority check already enforced",
    }
    result = apply_verdict(cand, verdict, _PATTERN_SIGNER)
    assert cand.status == "killed"
    assert cand.killed_by == "gate2"
    assert result["verdict"] == "kill"
    assert "q1_upstream_check" in result["yes_ids"]


def test_q5_yes_kills_candidate() -> None:
    cand = _cand()
    verdict = {
        "answers": [
            {"id": "q1_upstream_check", "yes": False, "evidence": ""},
            {"id": "q5_ack_by_prior_audit", "yes": True, "evidence": "OtterSec signed off"},
        ],
        "verdict": "kill",
    }
    result = apply_verdict(cand, verdict, _PATTERN_SIGNER)
    assert cand.status == "killed"
    assert result["verdict"] == "kill"


def test_model_verdict_kill_without_yes_id_still_kills() -> None:
    """Robustness: the Agent can drift on question ids; fall back on
    ``verdict_reply``."""
    cand = _cand()
    verdict = {"answers": [], "verdict": "kill", "summary": "obvious false positive"}
    result = apply_verdict(cand, verdict, _PATTERN_SIGNER)
    assert cand.status == "killed"
    assert result["verdict"] == "kill"


# ---------------------------------------------------------------------------
# DOWNGRADE path — Q2/Q3/Q4/Q6 lower severity by one rank, floor-limited.
# ---------------------------------------------------------------------------


def test_q2_yes_downgrades_one_rank() -> None:
    cand = _cand(severity=Severity.CRITICAL)
    verdict = {
        "answers": [
            {"id": "q2_intended_behavior", "yes": True, "evidence": "gated by constraint"}
        ],
        "verdict": "downgrade",
    }
    result = apply_verdict(cand, verdict, _PATTERN_SIGNER)
    assert cand.status == "downgraded"
    assert cand.severity == Severity.HIGH
    assert result["verdict"] == "downgrade"


def test_downgrade_respects_rule_severity_floor() -> None:
    """Missing-signer floor is High; even if Agent voted downgrade the
    candidate never drops below High."""
    cand = _cand(severity=Severity.HIGH)
    verdict = {
        "answers": [
            {"id": "q3_admin_only", "yes": True, "evidence": "admin-gated by ACL"}
        ],
        "verdict": "downgrade",
    }
    result = apply_verdict(cand, verdict, _PATTERN_SIGNER)
    assert cand.status == "downgraded"
    # High → Medium then floored back to High.
    assert cand.severity == Severity.HIGH
    assert result["verdict"] == "downgrade"


def test_downgrade_without_floor_pattern_drops_one_rank() -> None:
    cand = _cand(severity=Severity.HIGH)
    verdict = {
        "answers": [{"id": "q6_public_data", "yes": True, "evidence": "pubkey only"}],
        "verdict": "downgrade",
    }
    apply_verdict(cand, verdict, None)
    assert cand.severity == Severity.MEDIUM


# ---------------------------------------------------------------------------
# KEEP path — no YES fires and Agent voted keep.
# ---------------------------------------------------------------------------


def test_all_no_keeps_candidate_live() -> None:
    cand = _cand()
    verdict = {
        "answers": [
            {"id": f"q{i + 1}_stub", "yes": False, "evidence": ""} for i in range(6)
        ],
        "verdict": "keep",
        "summary": "no counter-question flipped the finding",
    }
    result = apply_verdict(cand, verdict, _PATTERN_SIGNER)
    assert cand.status == "live"
    assert result["verdict"] == "keep"


def test_not_live_candidate_is_skipped() -> None:
    cand = _cand()
    cand.kill(gate="gate1", reason="already killed")
    verdict = {"answers": [], "verdict": "kill"}
    result = apply_verdict(cand, verdict, _PATTERN_SIGNER)
    assert result["verdict"] == "skipped"
    assert cand.killed_by == "gate1"
    assert result["applied"] is False


# ---------------------------------------------------------------------------
# Thin-tool adapter — dict-in / dict-out contract
# ---------------------------------------------------------------------------


def test_tool_execute_accepts_candidate_dict() -> None:
    cand_dict = _cand(severity=Severity.MEDIUM).to_dict()
    verdict = {
        "answers": [{"id": "q4_economic", "yes": True, "evidence": "ROI << 1"}],
        "verdict": "downgrade",
    }
    out = cq_execute(
        candidate=cand_dict,
        verdict=verdict,
        pattern=_PATTERN_SYSVAR,
    )
    assert out["verdict"] == "downgrade"
    assert out["candidate"]["status"] == "downgraded"
    # Rule floor for sysvar_spoofing is Medium; Medium → Low gets floored back to Medium.
    assert out["candidate"]["severity"] == "Medium"
