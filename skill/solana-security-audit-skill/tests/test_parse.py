# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""P2.2.3 — Parse unit tests.

Pins the 5-fixture contract and four degradation paths so future refactors
of :mod:`tools.solana_parse` can't silently regress the structured output the
downstream scanner depends on.
"""

from __future__ import annotations

import pytest

from core.types import ParsedContract
from tools.solana_parse import execute, parse_file, parse_source

from .conftest import FIXTURES_ROOT, fixture_path

FIXTURE_NAMES = [
    "01_missing_signer",
    "02_missing_owner",
    "03_integer_overflow",
    "04_arbitrary_cpi",
    "05_clean_contract",
]


def _by_name(items: list[dict], name: str) -> dict | None:
    for item in items:
        if item.get("name") == name:
            return item
    return None


# ---------------------------------------------------------------------------
# Per-fixture structural assertions
# ---------------------------------------------------------------------------


def test_parse_01_missing_signer_surfaces_authority_as_accountinfo() -> None:
    pc = parse_file(fixture_path("01_missing_signer"))
    assert pc.parse_error is None
    assert len(pc.functions) >= 1
    withdraw_struct = _by_name(pc.accounts, "Withdraw")
    assert withdraw_struct is not None, "Withdraw struct should be parsed"
    authority = _by_name(withdraw_struct["fields"], "authority")
    assert authority is not None
    assert authority["type_category"] == "AccountInfo"
    assert pc.metadata.get("declare_id")


def test_parse_02_missing_owner_surfaces_config_accountinfo() -> None:
    pc = parse_file(fixture_path("02_missing_owner"))
    assert pc.parse_error is None
    update = _by_name(pc.accounts, "UpdateConfig")
    assert update is not None
    config_field = _by_name(update["fields"], "config")
    assert config_field is not None
    assert config_field["type_category"] == "AccountInfo"
    admin_field = _by_name(update["fields"], "admin")
    assert admin_field is not None
    assert admin_field["type_category"] == "Signer"


def test_parse_03_integer_overflow_has_two_instructions() -> None:
    pc = parse_file(fixture_path("03_integer_overflow"))
    assert pc.parse_error is None
    instr_names = {i["name"] for i in pc.instructions}
    assert {"deposit", "withdraw"} <= instr_names
    assert len(pc.instructions) == 2


def test_parse_04_arbitrary_cpi_has_seeds_anchor_attr() -> None:
    pc = parse_file(fixture_path("04_arbitrary_cpi"))
    assert pc.parse_error is None
    seeds_attrs = [a for a in pc.anchor_attrs if "seeds" in a]
    assert len(seeds_attrs) >= 1, "04 fixture exposes vault seeds"
    # The vault field should carry seeds/bump attrs on its own struct.
    forward = _by_name(pc.accounts, "Forward")
    assert forward is not None
    vault = _by_name(forward["fields"], "vault")
    assert vault is not None
    assert any("seeds" in attr for attr in vault["attrs"])


def test_parse_05_clean_contract_has_three_seeds_and_init_bump_on_vault() -> None:
    pc = parse_file(fixture_path("05_clean_contract"))
    assert pc.parse_error is None
    seeds_attrs = [a for a in pc.anchor_attrs if "seeds" in a]
    assert len(seeds_attrs) == 3, f"expected 3 seeds attrs, got {len(seeds_attrs)}"
    initialize = _by_name(pc.accounts, "Initialize")
    assert initialize is not None
    vault = _by_name(initialize["fields"], "vault")
    assert vault is not None, "Initialize.vault should be parsed"
    # The vault field carries the full #[account(init, payer=..., seeds=[...], bump)]
    # block — after _find_account_attrs strips the outer #[account(...)],
    # attrs list should include at least one entry containing init/seeds/bump.
    flags = {key for attr in vault["attrs"] for key in attr.keys()}
    assert {"init", "seeds", "bump"} <= flags


# ---------------------------------------------------------------------------
# Degradation paths — must return parse_error, never raise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_input",
    [
        "",
        "   \n\n\t  ",
    ],
    ids=["empty", "whitespace"],
)
def test_parse_empty_source_degrades(bad_input: str) -> None:
    pc = parse_source(bad_input)
    assert pc.parse_error == "empty source"
    assert pc.functions == []
    assert pc.accounts == []


def test_parse_garbage_text_does_not_raise() -> None:
    """Non-Rust text should parse to empty structures without raising."""
    pc = parse_source("This is definitely not Rust; just plain English.\n\nAnd a :: colon.")
    # parse_error is only set on empty / I/O failures — garbage returns empty lists.
    assert pc.parse_error is None
    assert pc.functions == []
    assert pc.accounts == []


def test_parse_none_is_handled_gracefully() -> None:
    """parse_source should never raise even for obviously wrong inputs."""
    pc = parse_source(None)  # type: ignore[arg-type]
    assert pc.parse_error is not None


def test_parse_missing_file_returns_parse_error() -> None:
    pc = parse_file(FIXTURES_ROOT / "does_not_exist.rs")
    assert pc.parse_error is not None
    assert "not found" in pc.parse_error.lower()


# ---------------------------------------------------------------------------
# Round-trip + generics preservation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_parse_round_trip_through_dict(name: str) -> None:
    pc = parse_file(fixture_path(name))
    data = pc.to_dict()
    restored = ParsedContract.from_dict(data)
    assert restored.to_dict() == data


def test_parse_preserves_lifetime_generic_types() -> None:
    """``Account<'info, Vault>`` must survive the type scanner's comma tracking."""
    pc = parse_file(fixture_path("05_clean_contract"))
    initialize = _by_name(pc.accounts, "Initialize")
    assert initialize is not None
    vault = _by_name(initialize["fields"], "vault")
    assert vault is not None
    assert "Account<'info, Vault>" in vault["ty"]


def test_execute_tool_matches_parse_source() -> None:
    """The OpenHarness ``execute`` wrapper should round-trip through to_dict."""
    source = fixture_path("01_missing_signer").read_text(encoding="utf-8")
    direct = parse_source(source).to_dict()
    viaexec = execute(code=source)
    assert viaexec["functions"] == direct["functions"]
    assert viaexec["accounts"] == direct["accounts"]
