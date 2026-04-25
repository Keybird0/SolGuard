# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""``solana_seven_q`` — Gate4 thin tool adapter.

Wraps :func:`ai.judge.seven_q_gate.apply` so the outer Agent can run the
deterministic 7-Question Gate (workflow.md §6.2) after Gate3. No LLM:
every answer is derived from the Gate2/Gate3 ledger plus KB metadata.
"""

from __future__ import annotations

from typing import Any

from ai.agents.types import Candidate, candidate_from_dict
from ai.judge import seven_q_gate

__all__ = ["SolanaSevenQTool", "execute"]


def _hydrate(items: list[Any]) -> list[Candidate]:
    out: list[Candidate] = []
    for it in items or []:
        if isinstance(it, Candidate):
            out.append(it)
        elif isinstance(it, dict):
            out.append(candidate_from_dict(it))
    return out


def execute(
    candidates: list[Any] | None = None,
    kb_patterns: list[dict[str, Any]] | None = None,
    source_code: str = "",
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness entry point for ``solana_seven_q``.

    Returns the summary from :func:`seven_q_gate.apply` plus the mutated
    candidate list (``candidates[i].to_dict()``) so the caller can feed
    survivors into ``solana_judge_lite``.
    """
    cands = _hydrate(candidates or [])
    summary = seven_q_gate.apply(
        cands,
        kb_patterns=kb_patterns or [],
        source_code=source_code or "",
    )
    return {
        **summary,
        "candidates": [c.to_dict() for c in cands],
    }


class SolanaSevenQTool:
    """OpenHarness Tool class — thin wrapper."""

    name: str = "solana_seven_q"
    version: str = "v0.1.0"

    def execute(
        self,
        candidates: list[Any] | None = None,
        kb_patterns: list[dict[str, Any]] | None = None,
        source_code: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        return execute(
            candidates=candidates,
            kb_patterns=kb_patterns,
            source_code=source_code,
            **kwargs,
        )
