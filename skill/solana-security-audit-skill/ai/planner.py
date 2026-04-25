# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""AI-first audit planner.

Given the normalized input envelope from solguard-server (a list of
``NormalizedInput`` entries, each carrying ``rootDir``/``primaryFile``/
``files``), this module produces an *audit plan*: the concrete list of
Rust files to audit, each annotated with a ``role`` (primary target /
comparison sample), ``priority``, and optional ``expectedBugClasses``.

The planner has two modes:

* **Deterministic** — repo-shape heuristics only. Always available.
  Handles the three shapes we care about:

  1. ``benchmark_repo`` — Sealevel-Attacks-style ``programs/<lesson>/
     {insecure,recommended,secure}/src/lib.rs``. We mark every
     ``insecure`` sample as a primary target and attach its sibling
     ``recommended`` / ``secure`` as comparison files.
  2. ``anchor_workspace`` — ``programs/<name>/src/lib.rs`` (+ optional
     sibling crates under ``programs/<name>/src/`` modules). Every
     program becomes its own target.
  3. ``single_program`` — a bare ``src/lib.rs`` or a lone ``.rs``
     fixture (our phase-2 fixtures fall into this bucket). Single
     target, no comparison.

* **LLM-assisted** — if an Anthropic/OpenAI key is configured AND the
  deterministic planner produced more than a tiny number of targets, we
  ask an LLM to reorder / filter them. If anything goes wrong (missing
  key, parse error, rate-limit) we silently use the deterministic plan.

The AI-first architecture is intentional: scanners are evidence
providers, not the audit entrypoint. Even when parser/scanner fail or
return 0 hints, ``run_audit`` still walks the plan and calls the LLM
code reviewer on each target.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "AuditTarget",
    "build_inventory",
    "plan_audit_targets",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AuditTarget:
    """A single file we plan to audit.

    ``role`` is a free-form slug; current known values are
    ``insecure_sample``, ``recommended_sample``, ``secure_sample``,
    ``program``, ``fixture``.
    """

    file: str
    role: str
    priority: str = "medium"
    expected_bug_classes: list[str] = field(default_factory=list)
    comparison_files: list[str] = field(default_factory=list)
    lesson: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "role": self.role,
            "priority": self.priority,
            "expectedBugClasses": list(self.expected_bug_classes),
            "comparisonFiles": list(self.comparison_files),
            "lesson": self.lesson,
        }


# ---------------------------------------------------------------------------
# Inventory building
# ---------------------------------------------------------------------------


_SKIP_DIRS = {"target", "node_modules", ".git", ".yarn", "vendor"}
# We deliberately *don't* skip "tests" here: lesson repos often stage
# reference "solutions" under tests/ that are audit-relevant.
_MAX_FILES_PER_INPUT = 200


def _iter_rust_files(root: Path) -> Iterable[Path]:
    if not root.exists() or not root.is_dir():
        return
    stack = [root]
    count = 0
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in _SKIP_DIRS or entry.name.startswith("."):
                    continue
                stack.append(entry)
                continue
            if entry.suffix == ".rs" and entry.name != "build.rs":
                yield entry
                count += 1
                if count >= _MAX_FILES_PER_INPUT * 4:
                    return


def build_inventory(inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Walk every ``rust_source`` input and collect a low-cost file list.

    The returned dict has shape::

        {
          "entries": [
            {
              "rootDir": "/tmp/.../foo",
              "primaryFile": "...",
              "files": ["programs/a/insecure/src/lib.rs", ...],
              "has_cargo_toml": True,
              "origin": {"type": "github", "value": "..."}
            },
            ...
          ],
          "totalRustFiles": N
        }

    Each file path in ``files`` is stored **relative to ``rootDir``** so
    LLM prompts stay short; callers can rejoin via ``os.path.join`` when
    they need the absolute path.
    """
    entries: list[dict[str, Any]] = []
    total = 0
    for raw in inputs:
        if raw.get("kind") != "rust_source":
            continue
        root_dir = raw.get("rootDir")
        files_from_input = raw.get("files") if isinstance(raw.get("files"), list) else None
        if not root_dir:
            # Single-file fixtures: primaryFile only.
            primary = raw.get("primaryFile")
            if primary:
                entries.append(
                    {
                        "rootDir": None,
                        "primaryFile": primary,
                        "files": [primary],
                        "has_cargo_toml": False,
                        "origin": raw.get("origin"),
                    }
                )
                total += 1
            continue
        root_path = Path(root_dir)
        if files_from_input:
            # Trust the server-side collector — it already skipped target/.
            rel_files = [
                (f if not f.startswith(root_dir) else os.path.relpath(f, root_dir))
                for f in files_from_input
            ]
        else:
            rel_files = []
            for rust_path in _iter_rust_files(root_path):
                rel = os.path.relpath(str(rust_path), root_dir)
                rel_files.append(rel)
                if len(rel_files) >= _MAX_FILES_PER_INPUT:
                    break
        entry: dict[str, Any] = {
            "rootDir": root_dir,
            "primaryFile": raw.get("primaryFile"),
            "files": rel_files,
            "has_cargo_toml": (root_path / "Cargo.toml").exists(),
            "origin": raw.get("origin"),
        }
        entries.append(entry)
        total += len(rel_files)
    return {"entries": entries, "totalRustFiles": total}


# ---------------------------------------------------------------------------
# Deterministic planner
# ---------------------------------------------------------------------------


def _classify_variant(path_parts: tuple[str, ...]) -> str | None:
    """Return ``insecure`` / ``recommended`` / ``secure`` if this path matches
    the Sealevel-Attacks layout, else ``None``.
    """
    for variant in ("insecure", "recommended", "secure"):
        if variant in path_parts:
            return variant
    return None


def _lesson_of(rel_path: str) -> str | None:
    """Extract the lesson slug from ``programs/<lesson>/<variant>/src/lib.rs``.

    Returns ``None`` if the path does not follow the benchmark layout.
    """
    parts = Path(rel_path).parts
    if len(parts) < 5:
        return None
    if parts[0] != "programs":
        return None
    if parts[2] not in ("insecure", "recommended", "secure"):
        return None
    return parts[1]


def _bug_class_hints_for_lesson(lesson: str) -> list[str]:
    """Best-effort mapping from lesson folder name → likely bug classes.

    Used to nudge the AI reviewer toward the expected issue without
    being prescriptive — the LLM can still surface other findings.
    """
    low = lesson.lower()
    table = {
        "signer-authorization": ["missing_signer_check"],
        "signer": ["missing_signer_check"],
        "account-data-matching": ["account_data_matching"],
        "owner-checks": ["missing_owner_check"],
        "owner": ["missing_owner_check"],
        "type-cosplay": ["account_data_matching"],
        "initialization": ["uninitialized_account"],
        "arbitrary-cpi": ["arbitrary_cpi"],
        "duplicate-mutable-accounts": ["duplicate_account"],
        "bump-seed-canonicalization": ["pda_derivation_error"],
        "pda-sharing": ["pda_derivation_error"],
        "closing-accounts": ["closing_account_error"],
        "sysvar-address-checking": ["sysvar_spoofing"],
    }
    for key, bugs in table.items():
        if key in low:
            return bugs
    return []


def _abs_path(root_dir: str | None, rel: str) -> str:
    if not root_dir:
        return rel
    if os.path.isabs(rel):
        return rel
    return str(Path(root_dir) / rel)


def _plan_benchmark_entry(entry: dict[str, Any]) -> list[AuditTarget]:
    """Sealevel-Attacks-style repo: one target per insecure sample.

    ``recommended`` / ``secure`` siblings become comparison files so the
    AI reviewer can explicitly contrast patched vs vulnerable code.
    """
    root_dir = entry.get("rootDir")
    files: list[str] = entry.get("files") or []
    grouped: dict[str, dict[str, str]] = {}
    for rel in files:
        lesson = _lesson_of(rel)
        if not lesson:
            continue
        parts = Path(rel).parts
        variant = parts[2]
        grouped.setdefault(lesson, {})[variant] = rel

    targets: list[AuditTarget] = []
    for lesson in sorted(grouped.keys()):
        variants = grouped[lesson]
        insecure_rel = variants.get("insecure")
        if not insecure_rel:
            continue
        comparison_rels = [variants[v] for v in ("recommended", "secure") if v in variants]
        targets.append(
            AuditTarget(
                file=_abs_path(root_dir, insecure_rel),
                role="insecure_sample",
                priority="high",
                expected_bug_classes=_bug_class_hints_for_lesson(lesson),
                comparison_files=[_abs_path(root_dir, c) for c in comparison_rels],
                lesson=lesson,
            )
        )
    return targets


def _plan_anchor_workspace(entry: dict[str, Any]) -> list[AuditTarget]:
    """Anchor workspace: one target per ``programs/<name>/src/lib.rs``."""
    root_dir = entry.get("rootDir")
    files: list[str] = entry.get("files") or []
    targets: list[AuditTarget] = []
    seen: set[str] = set()
    for rel in files:
        parts = Path(rel).parts
        # Match programs/<name>/src/lib.rs exactly (no insecure/recommended/secure layer).
        if (
            len(parts) >= 4
            and parts[0] == "programs"
            and parts[-1] == "lib.rs"
            and parts[-2] == "src"
            and parts[2] != "insecure"
            and parts[2] != "recommended"
            and parts[2] != "secure"
        ):
            program_name = parts[1]
            if program_name in seen:
                continue
            seen.add(program_name)
            targets.append(
                AuditTarget(
                    file=_abs_path(root_dir, rel),
                    role="program",
                    priority="high",
                    lesson=program_name,
                )
            )
    return targets


def _plan_single(entry: dict[str, Any]) -> list[AuditTarget]:
    """Fallback planner: pick the primary file (or the first Rust file)."""
    root_dir = entry.get("rootDir")
    primary = entry.get("primaryFile")
    files: list[str] = entry.get("files") or []
    pick: str | None = None
    if primary:
        pick = primary if os.path.isabs(primary) else _abs_path(root_dir, primary)
    elif files:
        pick = _abs_path(root_dir, files[0])
    if not pick:
        return []
    role = "fixture" if not root_dir else "program"
    return [AuditTarget(file=pick, role=role, priority="high")]


def _plan_entry(entry: dict[str, Any]) -> list[AuditTarget]:
    files: list[str] = entry.get("files") or []
    has_benchmark_layout = any(_lesson_of(f) for f in files)
    if has_benchmark_layout:
        benchmark = _plan_benchmark_entry(entry)
        if benchmark:
            return benchmark
    workspace = _plan_anchor_workspace(entry)
    if workspace:
        return workspace
    return _plan_single(entry)


def _deterministic_plan(inventory: dict[str, Any]) -> dict[str, Any]:
    targets: list[AuditTarget] = []
    mode = "single_program"
    for entry in inventory.get("entries", []):
        planned = _plan_entry(entry)
        if planned and any(t.role == "insecure_sample" for t in planned):
            mode = "benchmark_repo"
        elif planned and all(t.role == "program" for t in planned) and len(planned) > 1:
            mode = "anchor_workspace"
        targets.extend(planned)
    return {
        "mode": mode,
        "targets": [t.to_dict() for t in targets],
        "planner": "deterministic",
    }


# ---------------------------------------------------------------------------
# LLM-assisted planning (optional, never fatal)
# ---------------------------------------------------------------------------


_PLANNER_SYSTEM_PROMPT = """\
You are SolGuard's *audit planner*. You are given a repository inventory
(list of Rust files) and must decide which files to audit and in what
order. You never produce security findings yourself — that's a later
stage. Return JSON only, no prose.

Repository modes you must recognize:

* ``benchmark_repo`` — Sealevel-Attacks layout with
  ``programs/<lesson>/{insecure,recommended,secure}/src/lib.rs``. Put
  every ``insecure`` file as a ``primary`` target with its siblings as
  ``comparisonFiles``. Priority = ``high``.
* ``anchor_workspace`` — one or more ``programs/<name>/src/lib.rs`` with
  no insecure/recommended/secure variants. Each program is its own
  target. Priority = ``high`` for the first few, ``medium`` after.
* ``single_program`` — just one program or a bare fixture. One target.

Output shape (strict):

```
{
  "mode": "benchmark_repo" | "anchor_workspace" | "single_program" | "docs_only",
  "targets": [
    {
      "file": "<absolute or repo-rooted path>",
      "role": "insecure_sample" | "program" | "fixture",
      "priority": "high" | "medium" | "low",
      "expectedBugClasses": ["missing_signer_check", ...],
      "comparisonFiles": ["programs/.../recommended/src/lib.rs"],
      "lesson": "<lesson slug or null>"
    }
  ]
}
```

Never invent files that are not in the inventory. If nothing is
auditable, return an empty ``targets`` array and set ``mode`` to
``docs_only``.
"""


def _call_llm_planner(
    inventory: dict[str, Any],
    deterministic: dict[str, Any],
    provider: str,
) -> dict[str, Any] | None:
    """Optional LLM re-ranking. Returns ``None`` on any failure so callers
    can fall back to the deterministic plan.
    """
    try:  # pragma: no cover — network path
        from .analyzer import AIAnalyzer

        analyzer = AIAnalyzer(provider=provider)  # type: ignore[arg-type]
        if not analyzer.api_key:
            return None
        # Build a lean user prompt. We include the deterministic plan as a
        # seed so the model has a sensible default to edit.
        inventory_slim = {
            "entries": [
                {
                    "rootDir": e.get("rootDir"),
                    "primaryFile": e.get("primaryFile"),
                    "fileCount": len(e.get("files") or []),
                    # Keep only the first N files to cap prompt size; the
                    # deterministic plan already picked the important ones.
                    "sampleFiles": (e.get("files") or [])[:60],
                }
                for e in inventory.get("entries", [])
            ],
            "totalRustFiles": inventory.get("totalRustFiles", 0),
        }
        user_prompt = (
            "## repository_inventory\n"
            f"```json\n{json.dumps(inventory_slim, ensure_ascii=False)}\n```\n\n"
            "## deterministic_plan\n"
            f"```json\n{json.dumps(deterministic, ensure_ascii=False)}\n```\n\n"
            "Return the updated plan as a strict JSON object following "
            "the schema from the system prompt."
        )

        # We reuse the analyzer's provider dispatch but with our own system
        # prompt — the simplest hack is to temporarily swap it.
        analyzer._system_prompt = _PLANNER_SYSTEM_PROMPT  # type: ignore[attr-defined]
        raw_text, _usage = analyzer._invoke_with_retry(user_prompt)  # type: ignore[attr-defined]
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            return None
        targets_raw = parsed.get("targets")
        if not isinstance(targets_raw, list):
            return None
        parsed["planner"] = "llm"
        return parsed
    except Exception:  # noqa: BLE001
        return None


def plan_audit_targets(
    inputs: list[dict[str, Any]],
    provider: str | None = None,
    *,
    inventory: dict[str, Any] | None = None,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    """Entry point. Always returns a plan; the ``planner`` key records the
    actual source (``deterministic`` vs ``llm``).

    The LLM path is attempted when *all* of:

    * ``provider`` is a non-empty string.
    * ``use_llm`` is True (or None + env ``SOLGUARD_PLANNER_LLM=1``).
    * The deterministic plan has at least 2 targets.

    On any LLM failure (no key, network, bad JSON), we silently fall
    back to the deterministic plan so the orchestrator never blocks.
    """
    if inventory is None:
        inventory = build_inventory(inputs)
    deterministic = _deterministic_plan(inventory)

    should_use_llm = use_llm
    if should_use_llm is None:
        should_use_llm = os.environ.get("SOLGUARD_PLANNER_LLM") == "1"
    if provider and should_use_llm and len(deterministic.get("targets", [])) >= 2:
        llm_plan = _call_llm_planner(inventory, deterministic, provider)
        if llm_plan is not None:
            return llm_plan
    return deterministic
