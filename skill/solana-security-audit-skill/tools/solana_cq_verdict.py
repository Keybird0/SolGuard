# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""``solana_cq_verdict`` — Gate2 deterministic landing adapter.

Takes a single candidate + the 6-question ``verdict`` JSON produced by
the outer Agent (per ``references/l4-judge-playbook.md §2``), plus the
matching KB pattern for severity floor, and applies the KILL / DOWNGRADE
/ KEEP action table.

This is the thin wrapper over
:func:`ai.judge.counter_question.apply_verdict`. No LLM.
"""

from __future__ import annotations

from typing import Any

from ai.agents.types import Candidate, candidate_from_dict
from ai.judge import counter_question

__all__ = ["SolanaCqVerdictTool", "execute"]


def execute(
    candidate: Any = None,
    verdict: dict[str, Any] | None = None,
    pattern: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness entry point for ``solana_cq_verdict``.

    Parameters
    ----------
    candidate
        :class:`Candidate` instance or its ``to_dict()`` form.
    verdict
        ``{"answers":[{"id","yes","evidence"},...], "verdict":"keep|downgrade|kill", "summary":"..."}``.
    pattern
        Matching KB pattern dict (used for severity floor). May be
        ``None``.
    """
    if candidate is None:
        raise ValueError("'candidate' argument is required")
    cand = candidate if isinstance(candidate, Candidate) else candidate_from_dict(candidate)
    result = counter_question.apply_verdict(cand, verdict or {}, pattern)
    return {
        **result,
        "candidate": cand.to_dict(),
    }


class SolanaCqVerdictTool:
    """OpenHarness Tool class — thin wrapper."""

    name: str = "solana_cq_verdict"
    version: str = "v0.1.0"

    def execute(
        self,
        candidate: Any = None,
        verdict: dict[str, Any] | None = None,
        pattern: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return execute(
            candidate=candidate,
            verdict=verdict,
            pattern=pattern,
            **kwargs,
        )
