# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""End-to-end smoke test for the skill-driven L3/L4 pipeline.

Exercises the 5 thin tools (``solana_kill_signal`` → ``solana_cq_verdict``
→ ``solana_attack_classify`` → ``solana_seven_q`` → ``solana_judge_lite``)
with **stub LLM verdicts** to confirm the Agent-friendly dict-in /
dict-out contract works end-to-end without touching any real model.

The scenario deliberately feeds:

* 3 candidates — one will be KILLed at Gate1 (secure signer guard
  present), one KILLed at Gate2 (LLM-voted kill), and one KEEP all the
  way through.
* A minimal KB patterns list sufficient for severity floors + Gate1
  regex to fire.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ai.agents.types import Candidate
from core.types import Severity
from tools.solana_attack_classify import execute as classify_execute
from tools.solana_cq_verdict import execute as cq_execute
from tools.solana_judge_lite import execute as judge_execute
from tools.solana_kill_signal import execute as kill_execute
from tools.solana_seven_q import execute as seven_q_execute


_KB_PATH = (
    Path(__file__).resolve().parent.parent
    / "knowledge"
    / "solana_bug_patterns.json"
)


@pytest.fixture(scope="module")
def kb_patterns() -> list[dict[str, Any]]:
    raw = json.loads(_KB_PATH.read_text(encoding="utf-8"))
    return raw["patterns"]


SOURCE_MIXED = """\
use anchor_lang::prelude::*;

#[program]
pub mod demo {
    use super::*;

    pub fn a_missing_signer(ctx: Context<A>) -> ProgramResult {
        msg!("hi {}", ctx.accounts.authority.key());
        Ok(())
    }

    pub fn b_missing_signer(ctx: Context<B>) -> Result<()> {
        msg!("ok {}", ctx.accounts.user.key());
        Ok(())
    }
}

#[derive(Accounts)]
pub struct A<'info> {
    pub authority: AccountInfo<'info>,
    pub admin: AccountInfo<'info>,
}

#[derive(Accounts)]
pub struct B<'info> {
    pub token_program: Program<'info, anchor_spl::token::Token>,
    pub user: Signer<'info>,
}
"""


def _mk_cand(rule_id: str, line: int, severity: Severity, source: str = "A2") -> Candidate:
    return Candidate(
        rule_id=rule_id,
        location=f"lib.rs:{line}",
        function_name=rule_id,
        severity=severity,
        title=rule_id.replace("_", " ").title(),
        reason="seed",
        recommendation="seed",
        code_snippet=None,
        source=source,  # type: ignore[arg-type]
    )


def _find_pattern(kb: list[dict[str, Any]], rule_id: str) -> dict[str, Any] | None:
    return next((p for p in kb if p.get("id") == rule_id), None)


def test_skill_playbook_smoke_end_to_end(kb_patterns: list[dict[str, Any]]) -> None:
    # -- L3 candidates (simulate A1+A2 merge) -------------------------------
    # Struct A (line 19-22) uses AccountInfo for both fields → Gate1 pass.
    # Struct B (line 25-28) uses Signer + Program wrapper → Gate1 kill for
    # both missing_signer_check and arbitrary_cpi hits inside it.
    cands = [
        _mk_cand("missing_signer_check", 20, Severity.HIGH, source="A1"),
        _mk_cand("missing_signer_check", 21, Severity.HIGH, source="A2"),
        _mk_cand("missing_signer_check", 27, Severity.HIGH, source="A2"),
        _mk_cand("arbitrary_cpi", 26, Severity.CRITICAL, source="A2"),
    ]
    cand_dicts = [c.to_dict() for c in cands]

    # -- Gate1 — Kill Signal (deterministic) --------------------------------
    g1 = kill_execute(
        candidates=cand_dicts,
        kb_patterns=kb_patterns,
        source_code=SOURCE_MIXED,
    )
    statuses_after_g1 = [c["status"] for c in g1["candidates"]]
    # Struct B's missing_signer + arbitrary_cpi should both be killed.
    assert statuses_after_g1.count("killed") >= 2
    # Struct A's two AccountInfo hits should survive.
    assert statuses_after_g1.count("live") >= 2

    # Drop kills; Gate2/3 only run on live candidates (Agent does this in the playbook).
    live_after_g1 = [c for c in g1["candidates"] if c["status"] == "live"]
    assert live_after_g1, "expected at least one live candidate into Gate2"

    # -- Gate2 — Counter-Question (Agent-played, stub verdicts) -------------
    g2_results = []
    g2_live: list[dict[str, Any]] = []
    for cand in live_after_g1:
        # Stub verdict: first live candidate gets KILLed via Q1 (upstream
        # check claimed to exist); the rest keep.
        if not g2_live and not any(r.get("kill") for r in g2_results):
            verdict = {
                "answers": [
                    {"id": "q1_upstream_check", "yes": True, "evidence": "pretend check"},
                ],
                "verdict": "kill",
                "summary": "stub kill",
            }
        else:
            verdict = {
                "answers": [
                    {"id": f"q{i+1}_stub", "yes": False, "evidence": ""} for i in range(6)
                ],
                "verdict": "keep",
                "summary": "stub keep",
            }
        pattern = _find_pattern(kb_patterns, str(cand.get("rule_id")))
        out = cq_execute(candidate=cand, verdict=verdict, pattern=pattern)
        g2_results.append({"kill": out["verdict"] == "kill"})
        if out["candidate"]["status"] == "live":
            g2_live.append(out["candidate"])

    assert any(r["kill"] for r in g2_results), "Gate2 stub should kill at least one"
    # One candidate should still be live for Gate3.
    assert g2_live, "expected at least one live candidate into Gate3"

    # -- Gate3 — Attack Scenario (Agent-played, stub scenario) --------------
    g3_live: list[dict[str, Any]] = []
    for cand in g2_live:
        scenario = {
            "setup": "attacker keypair",
            "call": "invoke ix with unauthorised authority",
            "result": "attacker recorded as authority",
            "cost": "5000 lamports",
            "detect": "no runtime guard",
            "net_roi": "> 1 when reused downstream",
        }
        out = classify_execute(candidate=cand, scenario=scenario)
        assert out["verdict"] == "keep"
        g3_live.append(out["candidate"])

    # -- Gate4 — 7-Question Gate (deterministic) ----------------------------
    g4 = seven_q_execute(
        candidates=g3_live,
        kb_patterns=kb_patterns,
        source_code=SOURCE_MIXED,
    )
    survivors = [c for c in g4["candidates"] if c["status"] == "live"]
    assert survivors, "expected at least one Gate4 survivor"

    # -- Judge Lite — post-processing --------------------------------------
    findings = [
        {
            "id": f"AI-{i:03d}",
            "rule_id": c.get("rule_id"),
            "severity": c.get("severity", "Medium"),
            "title": c.get("title", ""),
            "location": c.get("location", ""),
            "description": c.get("reason", ""),
            "impact": c.get("reason", ""),
            "recommendation": c.get("recommendation", ""),
            "code_snippet": None,
            "confidence": None,
        }
        for i, c in enumerate(survivors)
    ]
    jl = judge_execute(
        findings=findings,
        kb_patterns=kb_patterns,
        scanner_hints=[],
        scanner_status="assisted",
        provenance="ai",
    )
    assert jl["statistics"]["total"] == len(survivors)
    assert all(f.get("kill_signal", {}).get("judge") == "judge-lite" for f in jl["findings"])
    # Severity floor must have held the arbitrary_cpi survivor (if any) at Critical.
    for f in jl["findings"]:
        if f["rule_id"] == "arbitrary_cpi":
            assert f["severity"] == "Critical"
        if f["rule_id"] == "missing_signer_check":
            assert f["severity"] in {"High", "Critical"}


def test_skill_playbook_smoke_agent_can_pass_candidate_instances(
    kb_patterns: list[dict[str, Any]],
) -> None:
    """Contract check: thin tools also accept live Candidate objects,
    not just their dict form. This matters when a custom in-process
    caller stitches tools together without serialising."""
    cand = _mk_cand("missing_signer_check", 20, Severity.HIGH, source="A1")
    out = kill_execute(
        candidates=[cand],
        kb_patterns=kb_patterns,
        source_code=SOURCE_MIXED,
    )
    assert out["applied"] >= 0
    assert isinstance(out["candidates"], list)
    # Original Candidate was hydrated in-place; returned dict round-trips.
    assert out["candidates"][0]["rule_id"] == "missing_signer_check"
