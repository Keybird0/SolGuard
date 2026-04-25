# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Unit tests for Gate-3 deterministic landing (``solana_attack_classify``).

The Agent plays the 6-step attack scenario (SETUP/CALL/RESULT/COST/
DETECT/NET-ROI) per ``references/l4-judge-playbook.md §3``. The Python
code only decides KILL/DOWNGRADE/KEEP based on the resulting dict:

* CALL or RESULT empty / ``call_feasible=false`` → KILL
* NET ROI not positive → DOWNGRADE by one rank
* otherwise → KEEP and stash scenario on ``candidate.raw``
"""

from __future__ import annotations

from typing import Any

from ai.agents.types import Candidate
from ai.judge.attack_scenario import _is_empty, _sentiment, classify_scenario
from core.types import Severity
from tools.solana_attack_classify import execute as classify_execute


def _cand(severity: Severity = Severity.HIGH) -> Candidate:
    return Candidate(
        rule_id="missing_signer_check",
        location="lib.rs:14",
        function_name="log_message",
        severity=severity,
        title="Missing Signer Check",
        reason="stub",
        recommendation="stub",
        code_snippet=None,
        source="A2",
    )


# ---------------------------------------------------------------------------
# Textual heuristics (_is_empty / _sentiment) — must stay deterministic.
# ---------------------------------------------------------------------------


def test_is_empty_handles_common_sentinels() -> None:
    assert _is_empty(None) is True
    assert _is_empty("") is True
    assert _is_empty("   ") is True
    assert _is_empty("n/a") is True
    assert _is_empty("TBD") is True
    assert _is_empty("unknown") is True
    assert _is_empty("invoke ix") is False


def test_sentiment_classifies_roi_phrases() -> None:
    assert _sentiment("ROI > 1 when vault reused") is True
    assert _sentiment("attack is profitable across 3 txs") is True
    assert _sentiment("positive net income") is True
    assert _sentiment("not profitable at current gas") is False
    assert _sentiment("ROI < 1") is False
    assert _sentiment("negligible gain, negative ROI") is False
    assert _sentiment("") is False


# ---------------------------------------------------------------------------
# KILL path — CALL/RESULT empty or infeasible.
# ---------------------------------------------------------------------------


def test_empty_call_kills_candidate() -> None:
    cand = _cand()
    scenario = {
        "setup": "attacker keypair",
        "call": "",
        "result": "",
        "cost": "",
        "detect": "",
        "net_roi": "",
    }
    result = classify_scenario(cand, scenario)
    assert cand.status == "killed"
    assert cand.killed_by == "gate3"
    assert result["verdict"] == "kill"
    assert result["call_empty"] is True


def test_empty_result_kills_candidate() -> None:
    cand = _cand()
    scenario = {
        "setup": "attacker keypair",
        "call": "invoke malicious ix",
        "result": "n/a",
        "cost": "5000",
        "detect": "none",
        "net_roi": "",
    }
    result = classify_scenario(cand, scenario)
    assert cand.status == "killed"
    assert result["result_empty"] is True


def test_explicit_call_feasible_false_kills() -> None:
    cand = _cand()
    scenario = {
        "setup": "needs upgrade authority",
        "call": "upgrade program id",
        "result": "replaces code",
        "cost": "permissioned",
        "detect": "",
        "net_roi": "",
        "call_feasible": False,
    }
    result = classify_scenario(cand, scenario)
    assert cand.status == "killed"
    assert result["verdict"] == "kill"


# ---------------------------------------------------------------------------
# DOWNGRADE path — NET ROI negative.
# ---------------------------------------------------------------------------


def test_negative_roi_downgrades_one_rank() -> None:
    cand = _cand(severity=Severity.CRITICAL)
    scenario = {
        "setup": "attacker keypair",
        "call": "invoke ix",
        "result": "tiny skim",
        "cost": "5000 lamports",
        "detect": "easy",
        "net_roi": "< 1 — not profitable",
    }
    result = classify_scenario(cand, scenario)
    assert cand.status == "downgraded"
    assert cand.severity == Severity.HIGH
    assert result["verdict"] == "downgrade"


def test_explicit_net_roi_positive_false_downgrades() -> None:
    cand = _cand(severity=Severity.HIGH)
    scenario = {
        "setup": "attacker keypair",
        "call": "invoke ix",
        "result": "stale state",
        "cost": "5000",
        "detect": "runtime log",
        "net_roi": "breakeven",
        "net_roi_positive": False,
    }
    classify_scenario(cand, scenario)
    assert cand.status == "downgraded"
    assert cand.severity == Severity.MEDIUM


# ---------------------------------------------------------------------------
# KEEP path — full scenario + positive ROI.
# ---------------------------------------------------------------------------


def test_full_scenario_keeps_candidate_live() -> None:
    cand = _cand()
    scenario = {
        "setup": "attacker keypair",
        "call": "invoke log_message with attacker-authority",
        "result": "attacker key recorded as authority",
        "cost": "5000 lamports",
        "detect": "no runtime guard",
        "net_roi": "> 1 when downstream vault reused",
    }
    result = classify_scenario(cand, scenario)
    assert cand.status == "live"
    assert result["verdict"] == "keep"
    assert cand.raw["attack_scenario"]["call"].startswith("invoke log_message")


def test_not_live_candidate_is_skipped() -> None:
    cand = _cand()
    cand.kill(gate="gate1", reason="already killed")
    scenario = {
        "setup": "...",
        "call": "...",
        "result": "...",
        "cost": "...",
        "detect": "...",
        "net_roi": "> 1",
    }
    result = classify_scenario(cand, scenario)
    assert result["verdict"] == "skipped"
    assert result["applied"] is False


# ---------------------------------------------------------------------------
# Thin-tool adapter — dict-in / dict-out contract
# ---------------------------------------------------------------------------


def test_tool_execute_accepts_candidate_dict() -> None:
    cand_dict = _cand().to_dict()
    scenario = {
        "setup": "attacker signs",
        "call": "invoke ix",
        "result": "funds drained",
        "cost": "tx fee",
        "detect": "no logs",
        "net_roi": "> 1",
    }
    out = classify_execute(candidate=cand_dict, scenario=scenario)
    assert out["verdict"] == "keep"
    assert out["candidate"]["status"] == "live"
    # Trace should carry the scenario so Gate-4 Q1/Q6 can reuse.
    gate3 = out["candidate"]["gate_traces"]["gate3_scenario"]
    assert gate3["scenario"]["call"] == "invoke ix"
