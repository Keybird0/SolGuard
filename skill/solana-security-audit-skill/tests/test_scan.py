# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""P2.3.3 — Scan layer unit tests.

Pins the Phase 2 hint-scanner contract:

* Every fixture's ``expected_scan_rule_ids`` in ``ground_truth.yaml`` must be
  a subset of the rule ids emitted (extra defensive hints are fine).
* The clean fixture must stay silent for the three high-signal rules
  (``missing_signer_check`` / ``missing_owner_check`` / ``arbitrary_cpi``).
* The aggregator must isolate single-rule failures into ``scan_errors`` and
  still emit all other hints.
* Empty ``ParsedContract`` → no crashes, zero hints.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.types import ParsedContract
from tools import solana_scan
from tools.solana_parse import parse_file
from tools.solana_scan import SolanaScanTool, scan

from .conftest import fixture_path


def _actual_rule_ids(result: dict[str, Any]) -> set[str]:
    return {h["rule_id"] for h in result["hints"]}


# ---------------------------------------------------------------------------
# 5-fixture ground-truth parity (5 cases)
# ---------------------------------------------------------------------------


def test_scan_ground_truth_expected_rule_ids_are_subset(
    ground_truth: dict[str, Any],
) -> None:
    """For every fixture, expected_scan_rule_ids ⊆ actual_rule_ids."""
    for entry in ground_truth["fixtures"]:
        file_name = entry["file"]
        expected = set(entry.get("expected_scan_rule_ids", []))
        pc = parse_file(fixture_path(file_name))
        result = scan(pc)
        actual = _actual_rule_ids(result)
        assert expected <= actual, (
            f"{file_name}: expected_scan_rule_ids={expected} not subset of "
            f"actual={actual}"
        )


# ---------------------------------------------------------------------------
# Clean-fixture false-positive guards (3 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_id",
    ["missing_signer_check", "missing_owner_check", "arbitrary_cpi"],
)
def test_scan_clean_contract_zero_false_positives(rule_id: str) -> None:
    pc = parse_file(fixture_path("05_clean_contract"))
    result = scan(pc)
    matches = [h for h in result["hints"] if h["rule_id"] == rule_id]
    assert matches == [], (
        f"clean fixture should not trigger {rule_id}, got: {matches}"
    )


# ---------------------------------------------------------------------------
# Specific rule smoke tests (3 cases)
# ---------------------------------------------------------------------------


def test_scan_integer_overflow_fires_twice_on_fixture_03() -> None:
    pc = parse_file(fixture_path("03_integer_overflow"))
    result = scan(pc)
    hits = [h for h in result["hints"] if h["rule_id"] == "integer_overflow"]
    assert len(hits) == 2
    assert result["statistics"].get("integer_overflow") == 2


def test_scan_arbitrary_cpi_fires_once_on_fixture_04() -> None:
    pc = parse_file(fixture_path("04_arbitrary_cpi"))
    result = scan(pc)
    hits = [h for h in result["hints"] if h["rule_id"] == "arbitrary_cpi"]
    assert len(hits) == 1
    assert "ctx.accounts.target_program" in hits[0]["why"]


def test_scan_missing_signer_fires_on_fixture_01() -> None:
    pc = parse_file(fixture_path("01_missing_signer"))
    result = scan(pc)
    hits = [h for h in result["hints"] if h["rule_id"] == "missing_signer_check"]
    assert len(hits) == 1
    assert hits[0]["confidence"] == "low"
    assert hits[0]["references_anchor"] == "#missing_signer_check"


# ---------------------------------------------------------------------------
# Aggregator resilience (2 cases)
# ---------------------------------------------------------------------------


def test_scan_single_rule_failure_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """If one rule throws, scan_errors records it but other rules still fire."""

    def check_integer_overflow(_parsed: ParsedContract) -> list[dict[str, Any]]:
        raise RuntimeError("simulated failure")

    # Swap in a rule list where the injected rule fails while others succeed.
    monkeypatch.setattr(
        solana_scan,
        "_RULES",
        [
            solana_scan.check_missing_signer_check,
            check_integer_overflow,
            solana_scan.check_arbitrary_cpi,
        ],
    )
    pc = parse_file(fixture_path("01_missing_signer"))
    result = scan(pc)
    assert any(
        e.get("rule_id") == "integer_overflow"
        and "simulated failure" in e.get("error", "")
        for e in result["scan_errors"]
    )
    assert any(h["rule_id"] == "missing_signer_check" for h in result["hints"])


def test_scan_empty_parsed_contract_returns_no_hints() -> None:
    pc = ParsedContract(file_path="<empty>", source_code="")
    result = scan(pc)
    assert result["hints"] == []
    assert result["scan_errors"] == []
    assert result["statistics"]["total"] == 0


# ---------------------------------------------------------------------------
# Tool wrapper + statistics shape (2 cases)
# ---------------------------------------------------------------------------


def test_solana_scan_tool_execute_accepts_dict_form() -> None:
    pc = parse_file(fixture_path("03_integer_overflow"))
    tool = SolanaScanTool()
    direct = scan(pc)
    viaexec = tool.execute(parsed=pc.to_dict())
    # Both paths should produce the same rule_id frequency.
    assert direct["statistics"] == viaexec["statistics"]


def test_scan_statistics_total_matches_hints_length() -> None:
    for name in (
        "01_missing_signer",
        "02_missing_owner",
        "03_integer_overflow",
        "04_arbitrary_cpi",
        "05_clean_contract",
    ):
        pc = parse_file(fixture_path(name))
        result = scan(pc)
        assert result["statistics"]["total"] == len(result["hints"])
