# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Gate4 — 7-Question Gate (deterministic core + Gate3 heuristic reuse).

The 7 questions come from ``references/audit-sop.md §4.3.4``. They decide
whether a candidate has earned a spot in the Exploit-Analysis +
Remediation reports.

| # | Question                              | Source                  |
|---|---------------------------------------|-------------------------|
| 1 | Can it actually be exploited?         | Gate3 ``call_feasible`` |
| 2 | Is the impact within audit scope?     | deterministic (severity)|
| 3 | Is the root cause in-scope?           | deterministic (rule KB) |
| 4 | Does exploitation need privilege?     | KB + Gate2 heuristic    |
| 5 | Already ack'ed by prior audit?        | deterministic (raw flag)|
| 6 | Economically profitable?              | Gate3 ``net_roi_positive``|
| 7 | Public / already disclosed?           | deterministic (raw flag)|

Design decision (plan §3.3): keep Gate4 cheap. Re-use Gate3's scenario
fields and Gate2's YES/NO ledger so we never need another LLM round
trip for the core questions. The gate only KILLs when Q1/Q2/Q3 fail —
the rest drop into ``gate_traces`` as supporting notes.

On a KILL Gate4 stamps ``candidate.kill(gate="gate4", reason=...)``.
Otherwise the candidate survives into ``_judge_lite`` and the final
Finding list.
"""

from __future__ import annotations

from typing import Any

from ai.agents.types import Candidate

__all__ = ["apply", "Gate4Result"]


class Gate4Result(dict):
    pass


# Canonical Solana bug classes that make a finding "in scope". Anything
# whose rule_id does not match one of these (by alias or id) fails Q3.
_IN_SCOPE_RULE_ALIASES: set[str] = set()


def _load_in_scope_aliases(kb_patterns: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for p in kb_patterns:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if pid:
            ids.add(str(pid))
        for v in p.get("rule_ids", []) or []:
            ids.add(str(v))
        for v in p.get("aliases", []) or []:
            ids.add(str(v))
    return ids


def _rule_in_scope(cand: Candidate, aliases: set[str]) -> tuple[bool, bool]:
    """Return ``(in_scope, provisional)``.

    ``provisional=True`` means the answer is a "soft PASS" because we lack
    enough info to decide on Q3 alone — currently triggered by
    ``rule_id is None`` (A1 Explorer's "truly novel" finding). In that case
    Q3 should NOT KILL the candidate; we let Gate2/Gate3 evidence decide.

    Hard ``False`` (out of scope, will KILL) is reserved for rules that are
    explicitly outside the Solana KB (e.g. ``semgrep:python.lang.foo``) or
    are non-null but absent from the KB alias set.
    """
    if cand.rule_id is None:
        # A1 novel finding — no rule_id to look up. Provisional PASS so
        # Q3 doesn't single-handedly KILL valid novel discoveries; Gate2/3
        # already had their say.
        return True, True
    rid = cand.rule_id
    if rid in aliases:
        return True, False
    bare = rid.split(":", 1)[-1] if ":" in rid else None
    if bare and bare in aliases:
        return True, False
    # Any prefix that signals an external analyzer whose findings cannot
    # be attributed to our Solana KB is out of scope (hard fail).
    if ":" in rid and rid.split(":", 1)[0] in {"semgrep", "external", "js", "python"}:
        return False, False
    return False, False


def _severity_in_scope(cand: Candidate) -> bool:
    # Audit scope covers Info..Critical — we never drop a candidate on Q2
    # alone. This mirrors the SOP's "fit within scope" interpretation for
    # SolGuard where the scope is the full target program.
    return cand.severity is not None


def _acknowledged(cand: Candidate) -> bool:
    raw = cand.raw if isinstance(cand.raw, dict) else {}
    if raw.get("acknowledged") is True:
        return True
    gate2 = cand.gate_traces.get("gate2_counter")
    if isinstance(gate2, dict):
        yes = gate2.get("yes_ids") or []
        if any(str(i).startswith("q5_ack") for i in yes):
            return True
    return False


def _publicly_disclosed(cand: Candidate) -> bool:
    raw = cand.raw if isinstance(cand.raw, dict) else {}
    if raw.get("public_disclosure") is True:
        return True
    gate2 = cand.gate_traces.get("gate2_counter")
    if isinstance(gate2, dict):
        yes = gate2.get("yes_ids") or []
        if any(str(i).startswith("q6_public") for i in yes):
            return True
    return False


def _gate3_snapshot(cand: Candidate) -> dict[str, Any]:
    trace = cand.gate_traces.get("gate3_scenario")
    if isinstance(trace, dict):
        return trace
    return {}


def apply(
    candidates: list[Candidate],
    *,
    kb_patterns: list[dict[str, Any]],
    source_code: str,  # noqa: ARG001 — reserved for future Q4 LLM heuristic
) -> Gate4Result:
    """Run the 7-Question Gate. Mutates candidates in place.

    Returns a summary dict with per-question pass/fail counters so
    ``benchmark_summary.json`` can report KILL distribution.
    """
    aliases = _load_in_scope_aliases(kb_patterns)

    applied = 0
    killed = 0
    q_fail_counts: dict[str, int] = {f"q{i}": 0 for i in range(1, 8)}
    details: list[dict[str, Any]] = []

    for cand in candidates:
        if cand.status != "live":
            continue
        applied += 1
        gate3 = _gate3_snapshot(cand)

        # Q1 — exploitability. If Gate3 produced a scenario, trust it;
        # if Gate3 was not applied (lower severity, no LLM, ...), treat
        # Q1 as provisional PASS so we don't double-penalise the sample.
        gate3_applied = bool(gate3.get("applied"))
        if gate3_applied:
            call_empty = bool(gate3.get("call_empty"))
            result_empty = bool(gate3.get("result_empty"))
            q1_exploitable = not (call_empty or result_empty)
        else:
            q1_exploitable = True

        # Q2 — impact in scope. Present severity anywhere in the enum
        # range counts.
        q2_impact_in_scope = _severity_in_scope(cand)

        # Q3 — root cause in scope. Rule must match a KB pattern, except
        # ``rule_id=None`` (A1 novel finding) gets a provisional PASS so
        # Gate2/Gate3 evidence — not Q3 alone — decides the outcome.
        q3_root_in_scope, q3_provisional = _rule_in_scope(cand, aliases)

        # Q4 — privileged access requirement. KB-driven heuristic: if the
        # per-pattern ``counter_question_hints.q3_admin_only`` suggests
        # admin-only, flag that for the report. A positive admin-only
        # answer does **not** KILL here — it is routed into the trace so
        # the remediation writer can emphasise governance controls.
        q4_privileged_note: str | None = None
        gate2 = cand.gate_traces.get("gate2_counter")
        if isinstance(gate2, dict) and "q3_admin_only" in (gate2.get("yes_ids") or []):
            q4_privileged_note = "Gate2 flagged admin-only"

        # Q5 — acknowledged by prior audit.
        q5_ack = _acknowledged(cand)

        # Q6 — economically feasible. Reuse Gate3 NET ROI sentiment.
        if gate3_applied:
            q6_economic = bool(gate3.get("net_roi_positive"))
        else:
            q6_economic = True  # provisional

        # Q7 — publicly disclosed / permissionless by design.
        q7_public = _publicly_disclosed(cand)

        answers = {
            "q1_exploitable": q1_exploitable,
            "q2_impact_in_scope": q2_impact_in_scope,
            "q3_root_in_scope": q3_root_in_scope,
            "q3_provisional": q3_provisional,
            "q4_privileged_note": q4_privileged_note,
            "q5_acknowledged": q5_ack,
            "q6_economic": q6_economic,
            "q7_public_disclosure": q7_public,
        }

        kill_reasons: list[str] = []
        if not q1_exploitable:
            kill_reasons.append("Q1 not exploitable (Gate3 CALL/RESULT empty)")
            q_fail_counts["q1"] += 1
        if not q2_impact_in_scope:
            kill_reasons.append("Q2 impact out of scope")
            q_fail_counts["q2"] += 1
        if not q3_root_in_scope:
            kill_reasons.append("Q3 root cause out of scope (rule not in KB)")
            q_fail_counts["q3"] += 1
        if not q6_economic and gate3_applied:
            kill_reasons.append("Q6 economic infeasible (NET ROI negative)")
            q_fail_counts["q6"] += 1
        if q5_ack:
            kill_reasons.append("Q5 acknowledged by prior audit")
            q_fail_counts["q5"] += 1
        if q7_public:
            kill_reasons.append("Q7 already publicly disclosed / intended-public")
            q_fail_counts["q7"] += 1

        trace: dict[str, Any] = {
            "applied": True,
            "answers": answers,
            "kill_reasons": kill_reasons,
        }
        if kill_reasons:
            reason_txt = "; ".join(kill_reasons)
            cand.kill(gate="gate4", reason=reason_txt)
            killed += 1
            trace["verdict"] = "kill"
        else:
            trace["verdict"] = "keep"
        cand.gate_traces["gate4_seven_q"] = trace
        details.append(
            {
                "rule_id": cand.rule_id,
                "location": cand.location,
                "verdict": trace["verdict"],
                "kill_reasons": kill_reasons,
                "answers": answers,
            }
        )

    return Gate4Result(
        {
            "gate": "gate4_seven_q",
            "applied": applied,
            "killed": killed,
            "q_fail_counts": q_fail_counts,
            "details": details,
        }
    )
