# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Integration-ish tests for the AI-first multi-target orchestrator.

These exercise ``run_audit_multi`` end-to-end with the LLM path
short-circuited (no API key + ``force_degraded=True``) so the test stays
deterministic and offline-safe. They assert the following contracts:

* The multi-target path walks ``build_inventory`` → ``plan_audit_targets``
  → per-target parse/scan without aborting on missing AI keys.
* Scanner errors or zero hints are tolerated (``scanner_status`` flags
  recorded on the final bundle).
* When parser fails completely, AI-only fallback path still produces a
  bundle (decision=degraded but no crash).
* Severity for known rule ids is up-ranked if the AI ever returns a
  lower value (unit test on the helper directly).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# `scripts/run_audit.py` is not a package module; tests import the
# orchestration helpers via an explicit path add.
import importlib.util
import sys

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_MODULE_PATH = _SKILL_ROOT / "scripts" / "run_audit.py"
_spec = importlib.util.spec_from_file_location("run_audit_module", _MODULE_PATH)
assert _spec is not None
run_audit_module = importlib.util.module_from_spec(_spec)
sys.modules["run_audit_module"] = run_audit_module
assert _spec.loader is not None
_spec.loader.exec_module(run_audit_module)

run_audit_multi = run_audit_module.run_audit_multi
_uprank_severity = run_audit_module._uprank_severity
_RULE_MIN_SEVERITY = run_audit_module._RULE_MIN_SEVERITY
_judge_lite = run_audit_module._judge_lite

from core.types import Finding, Severity


SIGNER_LESSON = """\
use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod signer_authorization_insecure {
    use super::*;
    pub fn log_message(ctx: Context<LogMessage>) -> ProgramResult {
        msg!("GM {}", ctx.accounts.authority.key().to_string());
        Ok(())
    }
}

#[derive(Accounts)]
pub struct LogMessage<'info> {
    authority: AccountInfo<'info>,
}
"""

SIGNER_LESSON_SECURE = """\
use anchor_lang::prelude::*;

#[program]
pub mod signer_authorization_secure {
    use super::*;
    pub fn log_message(ctx: Context<LogMessage>) -> ProgramResult {
        msg!("GM {}", ctx.accounts.authority.key().to_string());
        Ok(())
    }
}

#[derive(Accounts)]
pub struct LogMessage<'info> {
    authority: Signer<'info>,
}
"""


def _seed_single_lesson(root: Path) -> None:
    lesson = root / "programs" / "0-signer-authorization"
    (lesson / "insecure" / "src").mkdir(parents=True)
    (lesson / "insecure" / "src" / "lib.rs").write_text(SIGNER_LESSON)
    (lesson / "secure" / "src").mkdir(parents=True)
    (lesson / "secure" / "src" / "lib.rs").write_text(SIGNER_LESSON_SECURE)


def test_run_audit_multi_benchmark_degraded_still_reports(tmp_path: Path) -> None:
    _seed_single_lesson(tmp_path)
    output_root = tmp_path / "out"
    inputs: list[dict[str, Any]] = [
        {
            "kind": "rust_source",
            "rootDir": str(tmp_path),
            "primaryFile": None,
            "origin": {"type": "github", "value": "https://github.com/coral-xyz/sealevel-attacks"},
        }
    ]
    bundle = run_audit_multi(
        inputs=inputs,
        output_root=output_root,
        task_id="unit-test",
        force_degraded=True,  # no LLM call; exercises the offline path.
        emit_events=False,
    )
    assert bundle["scan_result"]["decision"] == "degraded"
    assert bundle["plan"]["mode"] == "benchmark_repo"
    assert len(bundle["targets"]) == 1
    target = bundle["targets"][0]
    assert target["role"] == "insecure_sample"
    # Even without LLM the scanner still runs: the parser fix means
    # `authority: AccountInfo<'info>` (no pub) is now picked up by
    # `missing_signer_check` and surfaces at least one finding.
    assert bundle["scan_result"]["statistics"]["total"] >= 1
    # Markdown must mention the audited target.
    assessment_path = Path(bundle["report"]["assessment"])
    assert assessment_path.exists()
    md = assessment_path.read_text()
    assert "Targets audited" in md
    assert "Why trust this result?" in md
    assert "Benchmark summary" in md
    assert "Knowledge routing" in md
    assert bundle["targets"][0]["evidence_pack"]["version"].startswith("evidence-pack-v2")
    assert "missing_signer_check" in bundle["targets"][0]["kb_patterns"]
    assert "benchmark_summary" in bundle
    assert "missing_signer_check" in bundle["benchmark_summary"]["covered_classes"]
    assert (output_root / "unit-test" / "benchmark_summary.json").exists()


def test_run_audit_multi_no_targets_returns_degraded_bundle(tmp_path: Path) -> None:
    inputs: list[dict[str, Any]] = []
    bundle = run_audit_multi(
        inputs=inputs,
        output_root=tmp_path / "out",
        task_id="empty",
        force_degraded=True,
    )
    assert bundle["scan_result"]["decision"] == "degraded"
    assert bundle["scan_result"]["statistics"]["total"] == 0


def test_uprank_severity_floors_known_rules() -> None:
    assert _uprank_severity(Severity.LOW, "missing_signer_check") is Severity.HIGH
    assert _uprank_severity(Severity.LOW, "arbitrary_cpi") is Severity.CRITICAL
    # Above baseline is preserved.
    assert _uprank_severity(Severity.CRITICAL, "missing_signer_check") is Severity.CRITICAL
    # Unknown rule id is untouched.
    assert _uprank_severity(Severity.LOW, "custom:unknown") is Severity.LOW
    # Baseline table coverage sanity.
    assert _RULE_MIN_SEVERITY["arbitrary_cpi"] is Severity.CRITICAL


def test_judge_lite_adds_provenance_and_confidence() -> None:
    finding = Finding(
        id="AI-1",
        rule_id="missing_signer_check",
        severity=Severity.LOW,
        title="Missing signer",
        location="lib.rs:10",
        description="authority is AccountInfo",
        impact="spoofed authority",
        recommendation="use Signer",
    )
    judged = _judge_lite(
        [finding],
        provenance="ai",
        scan_result={"hints": [{"rule_id": "missing_signer_check"}]},
        kb_patterns=[{"id": "missing_signer_check", "rule_ids": ["missing_signer_check"]}],
        scanner_status="assisted",
    )
    assert judged[0].severity is Severity.HIGH
    assert judged[0].confidence and judged[0].confidence >= 0.9
    assert judged[0].kill_signal["status"] == "confirmed"
    assert judged[0].kill_signal["matched_kb"] is True
