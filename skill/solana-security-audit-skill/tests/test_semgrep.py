# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""P2.3.3 — Semgrep runner tests.

Semgrep is a heavy optional dependency; all tests that actually shell out to
the CLI are wrapped in ``@pytest.mark.skipif(not shutil.which("semgrep"))``.
The degradation tests never require semgrep to be installed and must always
run (proving the tool_error fallback still works on CI images where
semgrep is absent).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools.semgrep_runner import DEFAULT_RULES_DIR, SemgrepRunner, run

from .conftest import fixture_path


HAS_SEMGREP = shutil.which("semgrep") is not None
SEMGREP_REASON = "semgrep CLI not installed"


# ---------------------------------------------------------------------------
# Live semgrep smoke tests (skipped if binary missing)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_SEMGREP, reason=SEMGREP_REASON)
def test_semgrep_runs_on_missing_signer_fixture() -> None:
    target = fixture_path("01_missing_signer")
    result = run(target_path=target)
    assert isinstance(result, dict)
    assert "results" in result
    # The unchecked-account rule should match `authority: AccountInfo<'info>`.
    check_ids = {r.get("check_id", "").rsplit(".", 1)[-1] for r in result["results"]}
    assert "solana-unchecked-accountinfo-field" in check_ids


@pytest.mark.skipif(not HAS_SEMGREP, reason=SEMGREP_REASON)
def test_semgrep_clean_contract_produces_no_results() -> None:
    target = fixture_path("05_clean_contract")
    result = run(target_path=target)
    assert result["results"] == []


@pytest.mark.skipif(not HAS_SEMGREP, reason=SEMGREP_REASON)
def test_semgrep_returns_raw_json_shape() -> None:
    """AI-first contract: runner exposes check_id + start.line + extra.message."""
    result = run(target_path=fixture_path("03_integer_overflow"))
    assert result["results"], "03 fixture should produce arithmetic hits"
    sample = result["results"][0]
    assert "check_id" in sample
    assert "start" in sample and "line" in sample["start"]
    assert "extra" in sample


@pytest.mark.skipif(not HAS_SEMGREP, reason=SEMGREP_REASON)
def test_semgrep_tool_wrapper_matches_run() -> None:
    tool = SemgrepRunner()
    direct = run(target_path=fixture_path("04_arbitrary_cpi"))
    via = tool.execute(target_path=fixture_path("04_arbitrary_cpi"))
    assert direct["results"] == via["results"]


# ---------------------------------------------------------------------------
# Graceful-degradation tests (no semgrep required)
# ---------------------------------------------------------------------------


def test_semgrep_missing_target_yields_tool_error(tmp_path: Path) -> None:
    result = run(target_path=tmp_path / "does_not_exist.rs")
    assert result["results"] == []
    assert result["tool_error"] is not None
    assert "not found" in result["tool_error"].lower()


def test_semgrep_missing_rules_dir_yields_tool_error(tmp_path: Path) -> None:
    target = fixture_path("05_clean_contract")
    result = run(target_path=target, rules_dir=tmp_path / "no_rules_here")
    assert result["results"] == []
    assert result["tool_error"] is not None


def test_semgrep_empty_rules_dir_yields_tool_error(tmp_path: Path) -> None:
    """A directory with no *.yaml files must also degrade safely."""
    target = fixture_path("05_clean_contract")
    empty_rules = tmp_path / "empty_rules"
    empty_rules.mkdir()
    result = run(target_path=target, rules_dir=empty_rules)
    assert result["results"] == []
    assert result["tool_error"] is not None


def test_semgrep_default_rules_dir_resolves_inside_skill() -> None:
    assert DEFAULT_RULES_DIR.name == "semgrep-rules"
    assert DEFAULT_RULES_DIR.parent.name == "assets"


def test_semgrep_no_binary_path_handled_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when the binary is missing, runner must not raise."""
    monkeypatch.setattr("tools.semgrep_runner.shutil.which", lambda _name: None)
    result = run(target_path=fixture_path("05_clean_contract"))
    assert result["results"] == []
    assert result["tool_error"] is not None
    assert "not installed" in result["tool_error"].lower()
