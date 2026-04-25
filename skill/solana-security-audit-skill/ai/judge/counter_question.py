# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Gate2 — Counter-Question 6-question *deterministic landing*.

Since v0.8 the LLM side of Gate-2 is played by the outer Agent following
``references/l4-judge-playbook.md §2`` (System prompt + user template +
Solana hints). That Agent produces a ``verdict`` JSON dict; THIS module
takes the dict, the candidate, and the KB pattern, and applies the
deterministic action table (Q1/Q5 ⇒ KILL, others ⇒ DOWNGRADE) with a
per-rule severity floor.

The reason to keep this in Python (rather than yet another prompt):
``severity_floor``, ``kill_ids``, and the rank-math must be identical
across Agent runs for benchmark reproducibility. The Agent may drift on
which verdict string to emit; we enforce the ground truth here.

Public API (used by ``tools/solana_cq_verdict.py``):

* :func:`apply_verdict` — single-candidate dict-in / dict-out API.
"""

from __future__ import annotations

from typing import Any

from ai.agents.types import Candidate
from core.types import Severity

__all__ = ["apply_verdict", "Gate2Result"]


class Gate2Result(dict):
    """Summary dict returned by :func:`apply_verdict`."""


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 5,
    Severity.HIGH: 4,
    Severity.MEDIUM: 3,
    Severity.LOW: 2,
    Severity.INFO: 1,
}

_RANK_TO_SEV: dict[int, Severity] = {v: k for k, v in _SEVERITY_RANK.items()}


# Action table — must stay in sync with references/l4-judge-playbook.md §2.4.
_KILL_IDS: frozenset[str] = frozenset({"q1_upstream_check", "q5_ack_by_prior_audit"})
_DOWNGRADE_IDS: frozenset[str] = frozenset(
    {"q2_intended_behavior", "q3_admin_only", "q4_economic", "q6_public_data"}
)


def _enforce_min_severity_floor(cand: Candidate, rule_min: Severity | None) -> None:
    """Never downgrade below the per-rule baseline floor."""
    if rule_min is None:
        return
    if _SEVERITY_RANK[cand.severity] < _SEVERITY_RANK[rule_min]:
        cand.severity = rule_min


def _rule_min_severity(pattern: dict[str, Any] | None) -> Severity | None:
    if not pattern:
        return None
    raw = pattern.get("severity")
    if not raw:
        return None
    try:
        return Severity.from_value(str(raw))
    except ValueError:
        return None


def apply_verdict(
    candidate: Candidate,
    verdict: dict[str, Any],
    pattern: dict[str, Any] | None,
) -> Gate2Result:
    """Apply a Gate-2 verdict dict to one candidate (deterministic landing).

    Parameters
    ----------
    candidate
        Live :class:`Candidate` (will be mutated in place).
    verdict
        Dict shaped ``{"answers": [{"id","yes","evidence"}, ...],
        "verdict": "keep|downgrade|kill", "summary": "..."}``. The
        Agent produced this by playing the Gate-2 prompt per
        ``l4-judge-playbook §2``.
    pattern
        Matching KB pattern dict (used for severity-floor lookup). May
        be ``None`` when no pattern matches the candidate rule id — the
        candidate is still processed but without severity floor.

    Returns
    -------
    Gate2Result
        Dict with ``verdict``, ``yes_ids``, ``severity_after``, and the
        trace that was also stamped into ``candidate.gate_traces``.
    """
    if candidate.status != "live":
        trace = {"applied": False, "reason": f"candidate not live ({candidate.status})"}
        candidate.gate_traces["gate2_counter"] = trace
        return Gate2Result(
            {
                "gate": "gate2_counter_question",
                "applied": False,
                "verdict": "skipped",
                "yes_ids": [],
                "severity_after": candidate.severity.value,
                "trace": trace,
            }
        )

    answers_raw = verdict.get("answers") if isinstance(verdict, dict) else None
    answers: list[dict[str, Any]] = [
        a for a in (answers_raw or []) if isinstance(a, dict)
    ]
    yes_answers = [a for a in answers if a.get("yes") is True]
    yes_ids = [str(a.get("id") or "") for a in yes_answers if a.get("id")]
    model_verdict = str(verdict.get("verdict", "") or "").lower() if isinstance(verdict, dict) else ""
    summary = str(verdict.get("summary", "") or "") if isinstance(verdict, dict) else ""

    triggered_kill = any(qid in _KILL_IDS for qid in yes_ids)
    triggered_downgrade = any(qid in _DOWNGRADE_IDS for qid in yes_ids)

    trace: dict[str, Any] = {
        "applied": True,
        "answers": answers,
        "verdict_reply": model_verdict,
        "any_yes": bool(yes_answers),
        "yes_ids": yes_ids,
        "summary": summary,
    }

    if triggered_kill or model_verdict == "kill":
        reason = "; ".join(
            f"Q-{a.get('id')}: {a.get('evidence','')}" for a in yes_answers
        ) or summary or "Gate-2 voted kill"
        candidate.kill(gate="gate2", reason=str(reason))
        trace["verdict"] = "kill"
    elif triggered_downgrade or model_verdict == "downgrade":
        rank = _SEVERITY_RANK[candidate.severity]
        new_rank = max(1, rank - 1)
        target = _RANK_TO_SEV[new_rank]
        candidate.downgrade(target, gate="gate2", reason=summary)
        _enforce_min_severity_floor(candidate, _rule_min_severity(pattern))
        trace["verdict"] = "downgrade"
    else:
        trace["verdict"] = "keep"

    candidate.gate_traces["gate2_counter"] = trace
    return Gate2Result(
        {
            "gate": "gate2_counter_question",
            "applied": True,
            "verdict": trace["verdict"],
            "yes_ids": yes_ids,
            "severity_after": candidate.severity.value,
            "trace": trace,
        }
    )
