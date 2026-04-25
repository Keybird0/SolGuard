# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Gate3 — 6-step Attack Scenario *deterministic landing*.

Since v0.8 the LLM side of Gate-3 is played by the outer Agent following
``references/l4-judge-playbook.md §3`` (System prompt + user template +
per-pattern ``attack_scenario_template`` hints). That Agent produces a
``scenario`` JSON dict; THIS module takes the dict, the candidate, and
applies the KILL / DOWNGRADE / KEEP decision table:

* CALL empty / ``call_feasible=false`` / RESULT empty → **KILL**
* NET ROI sentiment negative (or ``net_roi_positive=false``) → DOWNGRADE by one rank
* otherwise → KEEP, store scenario at ``candidate.raw['attack_scenario']``
  so Gate-4 Q1 / Q6 can reuse.

The textual heuristics ``_is_empty`` and ``_sentiment`` must stay here
(not in a markdown SOP) because they define the ground truth for
benchmark comparisons; the Agent may drift on which sentiment phrase it
generates, so we classify against a fixed phrase whitelist.

Public API (used by ``tools/solana_attack_classify.py``):

* :func:`classify_scenario` — single-candidate dict-in / dict-out API.
"""

from __future__ import annotations

from typing import Any

from ai.agents.types import Candidate
from core.types import Severity

__all__ = ["classify_scenario", "Gate3Result", "_is_empty", "_sentiment"]


class Gate3Result(dict):
    pass


_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 5,
    Severity.HIGH: 4,
    Severity.MEDIUM: 3,
    Severity.LOW: 2,
    Severity.INFO: 1,
}

_DOWNGRADE_MAP: dict[int, Severity] = {
    5: Severity.HIGH,
    4: Severity.MEDIUM,
    3: Severity.LOW,
    2: Severity.INFO,
    1: Severity.INFO,
}


def _is_empty(text: str | None) -> bool:
    """Return ``True`` when the LLM's field is effectively empty."""
    if not text:
        return True
    s = str(text).strip().lower()
    return s == "" or s in {"n/a", "unknown", "tbd", "none", "?"}


def _sentiment(text: str | None) -> bool:
    """Return True when net_roi text reads positive.

    Tolerates SOP-style phrasing ("ROI > 1", "> 1 when vault reused",
    "attack is profitable"). Returns False for explicit negatives or
    clearly uneconomic wording ("< 1", "not profitable", "negligible
    gain").
    """
    if not text:
        return False
    lowered = str(text).lower().strip()
    if "not profitable" in lowered or "< 1" in lowered:
        return False
    if "not positive" in lowered or "negative" in lowered:
        return False
    if "> 1" in lowered or "≫ 1" in lowered or ">> 1" in lowered:
        return True
    if "profitable" in lowered and "not profitable" not in lowered:
        return True
    if "positive" in lowered:
        return True
    return False


def classify_scenario(
    candidate: Candidate,
    scenario: dict[str, Any],
) -> Gate3Result:
    """Apply the Gate-3 decision table to one candidate.

    Parameters
    ----------
    candidate
        Live :class:`Candidate` — will be mutated in place.
    scenario
        Dict produced by the outer Agent per
        ``l4-judge-playbook.md §3.3`` (keys: setup / call / result /
        cost / detect / net_roi / call_feasible / net_roi_positive).

    Returns
    -------
    Gate3Result
        Dict with ``verdict`` (``keep|downgrade|kill``), plus the
        derived booleans and the trace stamped on
        ``candidate.gate_traces['gate3_scenario']``.
    """
    if candidate.status != "live":
        trace = {"applied": False, "reason": f"candidate not live ({candidate.status})"}
        candidate.gate_traces["gate3_scenario"] = trace
        return Gate3Result(
            {
                "gate": "gate3_attack_scenario",
                "applied": False,
                "verdict": "skipped",
                "call_empty": False,
                "result_empty": False,
                "net_roi_positive": False,
                "trace": trace,
            }
        )

    scenario = scenario if isinstance(scenario, dict) else {}
    setup = scenario.get("setup")
    call = scenario.get("call")
    result = scenario.get("result")
    cost = scenario.get("cost")
    detect = scenario.get("detect")
    net_roi = scenario.get("net_roi")

    call_empty = _is_empty(call)
    result_empty = _is_empty(result)
    explicit_infeasible = scenario.get("call_feasible") is False
    explicit_net = scenario.get("net_roi_positive")
    net_positive = explicit_net if isinstance(explicit_net, bool) else _sentiment(net_roi)

    trace: dict[str, Any] = {
        "applied": True,
        "scenario": {
            "setup": setup,
            "call": call,
            "result": result,
            "cost": cost,
            "detect": detect,
            "net_roi": net_roi,
        },
        "call_empty": call_empty,
        "result_empty": result_empty,
        "call_feasible": not (call_empty or explicit_infeasible),
        "net_roi_positive": bool(net_positive),
    }

    if call_empty or result_empty or explicit_infeasible:
        candidate.kill(
            gate="gate3",
            reason="Attack Scenario CALL/RESULT empty — exploit not constructible",
        )
        trace["verdict"] = "kill"
    elif not net_positive:
        rank = _RANK[candidate.severity]
        target = _DOWNGRADE_MAP[rank]
        candidate.downgrade(target, gate="gate3", reason="NET ROI negative")
        trace["verdict"] = "downgrade"
    else:
        trace["verdict"] = "keep"

    candidate.gate_traces["gate3_scenario"] = trace
    candidate.raw["attack_scenario"] = trace["scenario"]

    return Gate3Result(
        {
            "gate": "gate3_attack_scenario",
            "applied": True,
            "verdict": trace["verdict"],
            "call_empty": call_empty,
            "result_empty": result_empty,
            "net_roi_positive": bool(net_positive),
            "trace": trace,
        }
    )
