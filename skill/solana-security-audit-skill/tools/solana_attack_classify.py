# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""``solana_attack_classify`` — Gate3 deterministic landing adapter.

Takes a single candidate + the 6-step ``scenario`` JSON produced by the
outer Agent (per ``references/l4-judge-playbook.md §3``) and applies the
KILL / DOWNGRADE / KEEP decision table via
:func:`ai.judge.attack_scenario.classify_scenario`.

No LLM. Pure dict-in / dict-out.
"""

from __future__ import annotations

from typing import Any

from ai.agents.types import Candidate, candidate_from_dict
from ai.judge import attack_scenario

__all__ = ["SolanaAttackClassifyTool", "execute"]


def execute(
    candidate: Any = None,
    scenario: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness entry point for ``solana_attack_classify``.

    Parameters
    ----------
    candidate
        :class:`Candidate` instance or its ``to_dict()`` form.
    scenario
        Dict shaped per ``l4-judge-playbook §3.3``: ``{setup, call,
        result, cost, detect, net_roi, call_feasible, net_roi_positive}``.
    """
    if candidate is None:
        raise ValueError("'candidate' argument is required")
    cand = candidate if isinstance(candidate, Candidate) else candidate_from_dict(candidate)
    result = attack_scenario.classify_scenario(cand, scenario or {})
    return {
        **result,
        "candidate": cand.to_dict(),
    }


class SolanaAttackClassifyTool:
    """OpenHarness Tool class — thin wrapper."""

    name: str = "solana_attack_classify"
    version: str = "v0.1.0"

    def execute(
        self,
        candidate: Any = None,
        scenario: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return execute(
            candidate=candidate,
            scenario=scenario,
            **kwargs,
        )
