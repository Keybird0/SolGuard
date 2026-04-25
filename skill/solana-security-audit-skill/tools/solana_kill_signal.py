# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""``solana_kill_signal`` — Gate1 thin tool adapter.

Wraps :func:`ai.judge.kill_signal.apply` for the skill-driven L4 pipeline.
Accepts a list of :class:`Candidate` dicts, the KB pattern table, and
the target source text. Runs the deterministic regex / AST kill-signal
checks and returns the mutated candidates plus a summary.

No LLM. Never throws on individual signal errors (captured per-signal in
``candidate.gate_traces.gate1_kill``).
"""

from __future__ import annotations

from typing import Any

from ai.agents.types import Candidate, candidate_from_dict
from ai.judge import kill_signal

__all__ = ["SolanaKillSignalTool", "execute"]


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
    """OpenHarness entry point for ``solana_kill_signal``.

    Parameters
    ----------
    candidates
        List of :class:`Candidate` dicts (from ``Candidate.to_dict()``)
        or ``Candidate`` instances. Mutated in place.
    kb_patterns
        ``knowledge/solana_bug_patterns.json["patterns"]`` list.
    source_code
        Full UTF-8 source of the audit target.

    Returns
    -------
    dict
        ``{gate, applied, killed, details, candidates}`` where
        ``candidates`` is the mutated list serialized back via
        :meth:`Candidate.to_dict`.
    """
    cands = _hydrate(candidates or [])
    summary = kill_signal.apply(
        cands,
        kb_patterns=kb_patterns or [],
        source_code=source_code or "",
    )
    return {
        **summary,
        "candidates": [c.to_dict() for c in cands],
    }


class SolanaKillSignalTool:
    """OpenHarness Tool class — thin wrapper so the runtime can discover it."""

    name: str = "solana_kill_signal"
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
