# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Unit tests for the AI-first audit planner.

These assertions pin the deterministic plan so Sealevel-Attacks-style
repos reliably produce one target per ``insecure`` sample with its
``recommended``/``secure`` siblings attached as comparison files.
The LLM-assisted path is covered by the (optional) benchmark scripts;
these tests stay offline.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai.planner import (
    AuditTarget,
    build_inventory,
    plan_audit_targets,
)


def _seed_sealevel_layout(root: Path) -> None:
    lessons = [
        "0-signer-authorization",
        "1-account-data-matching",
        "5-arbitrary-cpi",
    ]
    for lesson in lessons:
        for variant in ("insecure", "recommended", "secure"):
            dir_ = root / "programs" / lesson / variant / "src"
            dir_.mkdir(parents=True, exist_ok=True)
            (dir_ / "lib.rs").write_text(f"// {lesson}/{variant}\n")
    # Noise.
    target = root / "target" / "debug"
    target.mkdir(parents=True, exist_ok=True)
    (target / "ignored.rs").write_text("fn x() {}")


def test_build_inventory_sees_every_rust_file(tmp_path: Path) -> None:
    _seed_sealevel_layout(tmp_path)
    inputs = [
        {
            "kind": "rust_source",
            "rootDir": str(tmp_path),
            "primaryFile": str(tmp_path / "programs" / "0-signer-authorization" / "insecure" / "src" / "lib.rs"),
            "files": None,
            "origin": {"type": "github", "value": "https://github.com/coral-xyz/sealevel-attacks"},
        }
    ]
    inv = build_inventory(inputs)
    assert inv["totalRustFiles"] == 9
    assert len(inv["entries"]) == 1
    entry = inv["entries"][0]
    # Files are relative to rootDir and do NOT include target/ debris.
    assert all(not f.startswith("target/") for f in entry["files"])
    assert "programs/0-signer-authorization/insecure/src/lib.rs" in entry["files"]


def test_plan_benchmark_repo_marks_insecure_and_attaches_siblings(tmp_path: Path) -> None:
    _seed_sealevel_layout(tmp_path)
    inputs = [
        {
            "kind": "rust_source",
            "rootDir": str(tmp_path),
            "primaryFile": None,
            "origin": {"type": "github", "value": "https://github.com/coral-xyz/sealevel-attacks"},
        }
    ]
    plan = plan_audit_targets(inputs, provider=None, use_llm=False)
    assert plan["mode"] == "benchmark_repo"
    assert plan["planner"] == "deterministic"
    targets = plan["targets"]
    assert len(targets) == 3
    for t in targets:
        assert t["role"] == "insecure_sample"
        assert t["priority"] == "high"
        # Comparisons = recommended + secure for this lesson.
        assert len(t["comparisonFiles"]) == 2
        assert "/insecure/" in t["file"]
    lessons = sorted(t["lesson"] for t in targets)
    assert lessons == ["0-signer-authorization", "1-account-data-matching", "5-arbitrary-cpi"]


def test_plan_single_file_fixture_is_single_program(tmp_path: Path) -> None:
    rs = tmp_path / "fixture.rs"
    rs.write_text("fn main() {}")
    inputs = [
        {
            "kind": "rust_source",
            "rootDir": None,
            "primaryFile": str(rs),
            "origin": {"type": "github", "value": "file:fixture"},
        }
    ]
    plan = plan_audit_targets(inputs, provider=None, use_llm=False)
    assert plan["mode"] == "single_program"
    assert len(plan["targets"]) == 1
    assert plan["targets"][0]["file"] == str(rs)


def test_plan_anchor_workspace_picks_each_program(tmp_path: Path) -> None:
    for program in ("escrow", "vesting"):
        d = tmp_path / "programs" / program / "src"
        d.mkdir(parents=True, exist_ok=True)
        (d / "lib.rs").write_text("fn x(){}")
    inputs = [
        {
            "kind": "rust_source",
            "rootDir": str(tmp_path),
            "primaryFile": None,
            "origin": {"type": "github", "value": "https://example.com"},
        }
    ]
    plan = plan_audit_targets(inputs, provider=None, use_llm=False)
    assert plan["mode"] == "anchor_workspace"
    names = sorted(t["lesson"] for t in plan["targets"])
    assert names == ["escrow", "vesting"]


def test_plan_llm_fallback_is_silent_on_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If provider is set but no key is configured, planner silently falls back."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _seed_sealevel_layout(tmp_path)
    inputs = [
        {
            "kind": "rust_source",
            "rootDir": str(tmp_path),
            "primaryFile": None,
            "origin": {"type": "github", "value": "https://example.com"},
        }
    ]
    plan = plan_audit_targets(inputs, provider="anthropic", use_llm=True)
    # Deterministic still wins because the analyzer has no API key.
    assert plan["planner"] == "deterministic"
    assert plan["mode"] == "benchmark_repo"
