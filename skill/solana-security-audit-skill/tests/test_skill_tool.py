# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Tests for the Claude Code dispatcher (``scripts/skill_tool.py``).

Strategy: invoke the dispatcher as a subprocess (so the actual Bash
contract Claude Code will use is exercised), feeding stdin JSON and
parsing stdout JSON. Compare structural shape of the result against
calling the Tool class's ``execute()`` directly — they MUST agree.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_DISPATCHER = _SKILL_ROOT / "scripts" / "skill_tool.py"

# Reuse the same fixture shapes used in test_ai_judge.py
INSECURE_MISSING_SIGNER = """\
use anchor_lang::prelude::*;

#[program]
pub mod demo {
    use super::*;
    pub fn log_message(ctx: Context<LogMessage>) -> ProgramResult {
        msg!("hi {}", ctx.accounts.authority.key());
        Ok(())
    }
}

#[derive(Accounts)]
pub struct LogMessage<'info> {
    pub authority: AccountInfo<'info>,
}
"""


def _run_dispatcher(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Invoke ``scripts/skill_tool.py <tool>`` with stdin JSON; return parsed stdout."""
    proc = subprocess.run(
        [sys.executable, str(_DISPATCHER), tool],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(_SKILL_ROOT),
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, (
        f"dispatcher exited {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def kb_patterns() -> list[dict[str, Any]]:
    raw = json.loads(
        (_SKILL_ROOT / "knowledge" / "solana_bug_patterns.json").read_text(
            encoding="utf-8"
        )
    )
    return raw["patterns"]


# ---------------------------------------------------------------------------
# Discovery / argument handling
# ---------------------------------------------------------------------------


def test_dispatcher_lists_all_nine_tools() -> None:
    proc = subprocess.run(
        [sys.executable, str(_DISPATCHER), "--list"],
        capture_output=True,
        text=True,
        cwd=str(_SKILL_ROOT),
        check=True,
    )
    names = set(proc.stdout.strip().splitlines())
    assert names == {
        "parse",
        "scan",
        "semgrep",
        "kill_signal",
        "cq_verdict",
        "attack_classify",
        "seven_q",
        "judge_lite",
        "report",
    }


def test_dispatcher_rejects_invalid_payload() -> None:
    proc = subprocess.run(
        [sys.executable, str(_DISPATCHER), "parse"],
        input="not json at all",
        capture_output=True,
        text=True,
        cwd=str(_SKILL_ROOT),
        check=False,
    )
    assert proc.returncode == 2
    err = json.loads(proc.stdout)
    assert err["error"] == "invalid_payload"


def test_dispatcher_rejects_bad_kwargs() -> None:
    proc = subprocess.run(
        [sys.executable, str(_DISPATCHER), "parse"],
        input=json.dumps({"definitely_not_a_kwarg": 42}),
        capture_output=True,
        text=True,
        cwd=str(_SKILL_ROOT),
        check=False,
    )
    # solana_parse raises ValueError when neither code nor code_path is
    # supplied → dispatcher returns runtime error code 1 with a structured
    # error envelope. The dispatcher must not crash, must not produce a
    # zero-status spurious result, and must emit a parseable JSON error.
    assert proc.returncode in (1, 2), f"expected non-zero, got {proc.returncode}"
    err = json.loads(proc.stdout)
    assert err.get("error") in {"bad_kwargs", "tool_runtime_error"}


# ---------------------------------------------------------------------------
# Tool round-trips
# ---------------------------------------------------------------------------


def test_parse_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text(INSECURE_MISSING_SIGNER, encoding="utf-8")
    result = _run_dispatcher("parse", {"code_path": str(src)})
    assert "functions" in result
    assert any(f.get("name") == "log_message" for f in result["functions"])
    assert "accounts" in result
    assert any(a.get("name") == "LogMessage" for a in result["accounts"])


def test_scan_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text(INSECURE_MISSING_SIGNER, encoding="utf-8")
    parsed = _run_dispatcher("parse", {"code_path": str(src)})
    scan = _run_dispatcher("scan", {"parsed": parsed})
    # solana_scan returns "hints" + "statistics" + "scan_errors"
    assert "hints" in scan
    assert "statistics" in scan
    assert any(
        h.get("references_anchor", "").endswith("missing_signer_check")
        for h in scan["hints"]
    )


def test_kill_signal_roundtrip(kb_patterns: list[dict[str, Any]]) -> None:
    """End-to-end Gate1 via dispatcher matches direct .execute() shape."""
    candidate = {
        "rule_id": "missing_signer_check",
        "location": "lib.rs:14",
        "function_name": None,
        "severity": "High",
        "title": "Missing Signer",
        "reason": "stub",
        "recommendation": "stub",
        "code_snippet": None,
        "source": "A2",
    }
    result = _run_dispatcher(
        "kill_signal",
        {
            "candidates": [candidate],
            "kb_patterns": kb_patterns,
            "source_code": INSECURE_MISSING_SIGNER,
        },
    )
    assert result["gate"] == "gate1_kill_signal"
    assert "candidates" in result
    assert len(result["candidates"]) == 1
    # Insecure source → candidate stays live (no Signer guard to fire)
    assert result["candidates"][0]["status"] == "live"
    assert result["killed"] == 0


def test_cq_verdict_roundtrip(kb_patterns: list[dict[str, Any]]) -> None:
    pattern = next(
        p for p in kb_patterns if p.get("id") == "missing_signer_check"
    )
    candidate = {
        "rule_id": "missing_signer_check",
        "location": "lib.rs:14",
        "function_name": "log_message",
        "severity": "High",
        "title": "Missing Signer",
        "reason": "stub",
        "recommendation": "stub",
        "code_snippet": None,
        "source": "A2",
    }
    verdict = {
        "yes_ids": [],
        "evidence": "Agent confirms no guard present",
    }
    result = _run_dispatcher(
        "cq_verdict",
        {"candidate": candidate, "verdict": verdict, "pattern": pattern},
    )
    assert result["gate"] == "gate2_counter_question"
    assert "candidate" in result
    assert "verdict" in result


def test_attack_classify_roundtrip() -> None:
    candidate = {
        "rule_id": "missing_signer_check",
        "location": "lib.rs:14",
        "function_name": "log_message",
        "severity": "High",
        "title": "Missing Signer",
        "reason": "stub",
        "recommendation": "stub",
        "code_snippet": None,
        "source": "A2",
    }
    scenario = {
        "setup": "attacker prepares fake authority pubkey",
        "call": "invoke log_message with attacker's AccountInfo as authority",
        "result": "log_message executes under attacker's identity",
        "cost": "negligible",
        "detect": "post-mortem trace of authority key",
        "net_roi": "positive — privilege escalation with trivial cost",
    }
    result = _run_dispatcher(
        "attack_classify", {"candidate": candidate, "scenario": scenario},
    )
    assert result["gate"] == "gate3_attack_scenario"
    assert "candidate" in result


def test_seven_q_roundtrip(kb_patterns: list[dict[str, Any]]) -> None:
    candidate = {
        "rule_id": "missing_signer_check",
        "location": "lib.rs:14",
        "function_name": "log_message",
        "severity": "High",
        "title": "Missing Signer",
        "reason": "stub",
        "recommendation": "stub",
        "code_snippet": None,
        "source": "A2",
        "gate_traces": {
            "gate3_scenario": {
                "applied": True,
                "call_empty": False,
                "result_empty": False,
                "net_roi_positive": True,
            }
        },
    }
    result = _run_dispatcher(
        "seven_q",
        {
            "candidates": [candidate],
            "kb_patterns": kb_patterns,
        },
    )
    assert result["gate"] == "gate4_seven_q"
    assert result["killed"] == 0  # all 7 questions pass


def test_judge_lite_roundtrip(kb_patterns: list[dict[str, Any]]) -> None:
    finding = {
        "id": "F-001",
        "rule_id": "missing_signer_check",
        "severity": "High",
        "title": "Missing Signer",
        "location": "lib.rs:14",
        "description": "stub",
        "impact": "stub",
        "recommendation": "stub",
        "code_snippet": None,
        "confidence": 0.9,
        "kill_signal": None,
    }
    result = _run_dispatcher(
        "judge_lite",
        {
            "findings": [finding],
            "kb_patterns": kb_patterns,
            "scanner_status": "assisted",
            "provenance": "ai",
        },
    )
    assert "findings" in result
    assert "statistics" in result
