# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Unit tests for the **deterministic** Layer-4 gates.

Since v0.8 the LLM side of Gate-2 / Gate-3 is played by the outer Agent
per ``references/l4-judge-playbook.md``; their deterministic landing
logic is covered separately by ``test_cq_verdict.py`` and
``test_attack_classify.py``. This file therefore only exercises the
two gates that remained 100% Python:

* **Gate1** — Kill Signal (regex / AST)
* **Gate4** — 7-Question Gate (reuses the Gate3 ledger shape)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ai.agents.types import Candidate
from ai.judge import kill_signal, seven_q_gate
from core.types import Severity


_KB_PATH = (
    Path(__file__).resolve().parent.parent
    / "knowledge"
    / "solana_bug_patterns.json"
)


@pytest.fixture(scope="module")
def kb_patterns() -> list[dict[str, Any]]:
    raw = json.loads(_KB_PATH.read_text(encoding="utf-8"))
    return raw["patterns"]


def _cand(
    *,
    rule_id: str,
    line: int,
    severity: Severity = Severity.HIGH,
    source: str = "A2",
) -> Candidate:
    return Candidate(
        rule_id=rule_id,
        location=f"lib.rs:{line}",
        function_name=None,
        severity=severity,
        title=rule_id.replace("_", " ").title(),
        reason="stub",
        recommendation="stub",
        code_snippet=None,
        source=source,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Gate1 — Kill Signal
# ---------------------------------------------------------------------------


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


SECURE_MISSING_SIGNER = """\
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
    pub authority: Signer<'info>,
}
"""


def test_gate1_insecure_signer_stays_live(kb_patterns: list[dict[str, Any]]) -> None:
    cand = _cand(rule_id="missing_signer_check", line=14)
    summary = kill_signal.apply(
        [cand], kb_patterns=kb_patterns, source_code=INSECURE_MISSING_SIGNER
    )
    assert summary["killed"] == 0
    assert cand.status == "live"
    trace = cand.gate_traces["gate1_kill"]
    assert trace["applied"] is True
    assert trace["verdict"] == "pass"
    assert trace["signals_checked"], "gate1 should record checked signals"


def test_gate1_secure_signer_gets_killed(kb_patterns: list[dict[str, Any]]) -> None:
    cand = _cand(rule_id="missing_signer_check", line=14)
    summary = kill_signal.apply(
        [cand], kb_patterns=kb_patterns, source_code=SECURE_MISSING_SIGNER
    )
    assert summary["killed"] == 1
    assert cand.status == "killed"
    assert cand.killed_by == "gate1"
    trace = cand.gate_traces["gate1_kill"]
    assert trace["verdict"] == "kill"
    fired = {s["id"] for s in trace["signals_fired"]}
    assert "anchor_signer_type" in fired


SECURE_OWNER_VIA_ACCOUNT_WRAPPER = """\
#[derive(Accounts)]
pub struct DepositAccounts<'info> {
    pub vault: Account<'info, Vault>,
    pub user: Signer<'info>,
}

pub fn deposit(ctx: Context<DepositAccounts>) -> Result<()> {
    let balance = ctx.accounts.vault.balance;
    Ok(())
}
"""


INSECURE_OWNER = """\
#[derive(Accounts)]
pub struct DepositAccounts<'info> {
    pub vault: AccountInfo<'info>,
    pub user: Signer<'info>,
}

pub fn deposit(ctx: Context<DepositAccounts>) -> Result<()> {
    let decoded = Vault::try_from_slice(&ctx.accounts.vault.data.borrow())?;
    Ok(())
}
"""


def test_gate1_owner_check_guard_kills(kb_patterns: list[dict[str, Any]]) -> None:
    cand = _cand(rule_id="missing_owner_check", line=3)
    summary = kill_signal.apply(
        [cand],
        kb_patterns=kb_patterns,
        source_code=SECURE_OWNER_VIA_ACCOUNT_WRAPPER,
    )
    assert summary["killed"] == 1
    assert cand.status == "killed"


def test_gate1_owner_check_no_guard_passes(
    kb_patterns: list[dict[str, Any]],
) -> None:
    cand = _cand(rule_id="missing_owner_check", line=3)
    summary = kill_signal.apply(
        [cand], kb_patterns=kb_patterns, source_code=INSECURE_OWNER
    )
    assert summary["killed"] == 0
    assert cand.status == "live"


SECURE_ARBITRARY_CPI = """\
#[derive(Accounts)]
pub struct TransferAccounts<'info> {
    pub token_program: Program<'info, anchor_spl::token::Token>,
    pub user: Signer<'info>,
}

pub fn transfer_tokens(ctx: Context<TransferAccounts>) -> Result<()> {
    require_keys_eq!(ctx.accounts.token_program.key(), anchor_spl::token::ID);
    invoke(&spl_token::instruction::transfer(...)?, &accounts)?;
    Ok(())
}
"""


def test_gate1_arbitrary_cpi_program_wrapper_kills(
    kb_patterns: list[dict[str, Any]],
) -> None:
    cand = _cand(rule_id="arbitrary_cpi", line=9, severity=Severity.CRITICAL)
    summary = kill_signal.apply(
        [cand], kb_patterns=kb_patterns, source_code=SECURE_ARBITRARY_CPI
    )
    assert summary["killed"] == 1
    assert cand.status == "killed"


def test_gate1_unknown_rule_id_is_skipped(
    kb_patterns: list[dict[str, Any]],
) -> None:
    cand = _cand(rule_id="semgrep:something-weird", line=5)
    summary = kill_signal.apply(
        [cand], kb_patterns=kb_patterns, source_code=INSECURE_MISSING_SIGNER
    )
    assert summary["applied"] == 0
    trace = cand.gate_traces["gate1_kill"]
    assert trace["applied"] is False


# ---------------------------------------------------------------------------
# Gate4 — 7-Question Gate
# ---------------------------------------------------------------------------


def test_gate4_kills_when_call_missing(kb_patterns: list[dict[str, Any]]) -> None:
    cand = _cand(rule_id="missing_signer_check", line=14)
    # Simulate: Gate3 produced empty CALL but for some reason survived to gate4.
    cand.gate_traces["gate3_scenario"] = {
        "applied": True,
        "call_empty": True,
        "result_empty": True,
        "net_roi_positive": False,
        "scenario": {"call": "", "result": "", "net_roi": ""},
    }
    summary = seven_q_gate.apply(
        [cand], kb_patterns=kb_patterns, source_code=INSECURE_MISSING_SIGNER
    )
    assert summary["killed"] == 1
    assert cand.status == "killed"
    assert cand.killed_by == "gate4"


def test_gate4_keeps_when_all_gates_green(
    kb_patterns: list[dict[str, Any]],
) -> None:
    cand = _cand(rule_id="missing_signer_check", line=14)
    cand.gate_traces["gate3_scenario"] = {
        "applied": True,
        "call_empty": False,
        "result_empty": False,
        "net_roi_positive": True,
        "scenario": {
            "call": "invoke ix",
            "result": "funds drained",
            "net_roi": "roi > 1",
        },
    }
    summary = seven_q_gate.apply(
        [cand], kb_patterns=kb_patterns, source_code=INSECURE_MISSING_SIGNER
    )
    assert summary["killed"] == 0
    assert cand.status == "live"


def test_gate4_kills_out_of_scope_rule(
    kb_patterns: list[dict[str, Any]],
) -> None:
    """Q3 — root cause outside in-scope contracts → KILL."""
    cand = _cand(rule_id="semgrep:python.lang.foo", line=5)
    cand.gate_traces["gate3_scenario"] = {
        "applied": True,
        "call_empty": False,
        "result_empty": False,
        "net_roi_positive": True,
    }
    summary = seven_q_gate.apply(
        [cand], kb_patterns=kb_patterns, source_code=INSECURE_MISSING_SIGNER
    )
    assert cand.status == "killed"
    assert summary["killed"] == 1
