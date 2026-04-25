# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Shared pytest fixtures / path helpers.

The fixture contracts live at ``<repo_root>/test-fixtures/contracts/`` (one
level above the skill package) so backend + benchmark tools can share them.
Tests compute the path once via :data:`FIXTURES_ROOT`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

SKILL_ROOT: Path = Path(__file__).resolve().parent.parent
REPO_ROOT: Path = SKILL_ROOT.parent.parent
FIXTURES_ROOT: Path = REPO_ROOT / "test-fixtures" / "contracts"
GROUND_TRUTH_PATH: Path = FIXTURES_ROOT / "ground_truth.yaml"


def fixture_path(name: str) -> Path:
    """Return absolute path to a named Rust fixture.

    ``name`` can be given with or without the ``.rs`` suffix, e.g.
    ``fixture_path("01_missing_signer")`` or ``fixture_path("01_missing_signer.rs")``.
    """
    if not name.endswith(".rs"):
        name = f"{name}.rs"
    return FIXTURES_ROOT / name


def load_ground_truth() -> dict[str, Any]:
    """Load ``ground_truth.yaml`` into a Python dict.

    Raises ``FileNotFoundError`` if the file is missing — tests that depend on
    ground truth should skip rather than silently pass when the file moves.
    """
    if not GROUND_TRUTH_PATH.exists():
        raise FileNotFoundError(
            f"ground_truth.yaml not found at {GROUND_TRUTH_PATH}"
        )
    return yaml.safe_load(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def fixtures_root() -> Path:
    return FIXTURES_ROOT


@pytest.fixture(scope="session")
def ground_truth() -> dict[str, Any]:
    return load_ground_truth()
