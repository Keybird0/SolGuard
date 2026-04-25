# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Shared dataclass that flows through Layer-3 agents → Layer-4 judge gates.

``Candidate`` carries everything Gate1..Gate4 need (rule id, location, function
name, severity, textual fields, and a growing ``gate_traces`` trail). It is
deliberately kept JSON-serialisable so per-gate diagnostics end up in
``benchmark_summary.json`` without extra plumbing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from core.types import Finding, Severity

__all__ = [
    "Candidate",
    "candidate_from_dict",
    "candidate_to_finding",
    "finding_to_candidate",
    "CandidateStatus",
    "CandidateSource",
]


CandidateStatus = Literal["live", "killed", "downgraded"]
CandidateSource = Literal["A1", "A2", "A3", "scanner", "seed"]


@dataclass
class Candidate:
    """One in-flight audit finding between the agents and the judge.

    ``gate_traces`` accumulates per-gate results (``gate1_kill``,
    ``gate2_counter``, ``gate3_scenario``, ``gate4_seven_q``). ``status``
    starts as ``live``; any gate that KILLs the candidate flips it to
    ``killed`` and records ``killed_by``.
    """

    rule_id: str | None
    location: str
    function_name: str | None
    severity: Severity
    title: str
    reason: str
    recommendation: str
    code_snippet: str | None
    source: CandidateSource
    raw: dict[str, Any] = field(default_factory=dict)
    gate_traces: dict[str, Any] = field(default_factory=dict)
    status: CandidateStatus = "live"
    killed_by: str | None = None
    killed_reason: str | None = None

    # ----- mutation helpers ------------------------------------------------

    def kill(self, *, gate: str, reason: str) -> None:
        """Mark the candidate as KILLed by ``gate`` with a human reason."""
        self.status = "killed"
        self.killed_by = gate
        self.killed_reason = reason

    def downgrade(self, target: Severity, *, gate: str, reason: str) -> None:
        """Reduce severity only when strictly below current rank."""
        rank = {
            Severity.CRITICAL: 5,
            Severity.HIGH: 4,
            Severity.MEDIUM: 3,
            Severity.LOW: 2,
            Severity.INFO: 1,
        }
        if rank.get(target, 0) < rank.get(self.severity, 0):
            self.severity = target
            self.status = "downgraded"
            self.gate_traces.setdefault("downgrades", []).append(
                {"gate": gate, "to": target.value, "reason": reason}
            )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        return data

    # ----- classifier helpers ---------------------------------------------

    def is_high_or_critical(self) -> bool:
        return self.severity in {Severity.CRITICAL, Severity.HIGH}


# ---------------------------------------------------------------------------
# dict <-> Candidate conversion (used by thin tool wrappers so the Agent can
# pass Candidate JSON across the tool boundary)
# ---------------------------------------------------------------------------


def candidate_from_dict(data: dict[str, Any]) -> Candidate:
    """Rehydrate a :class:`Candidate` from its ``to_dict()`` form.

    Accepts the exact shape produced by :meth:`Candidate.to_dict` (with
    ``severity`` as a string) and is lenient about missing optional
    fields so the Agent can call thin tools with a minimal JSON payload.
    """
    sev_raw = data.get("severity", "Medium")
    try:
        severity = (
            sev_raw if isinstance(sev_raw, Severity) else Severity.from_value(str(sev_raw))
        )
    except ValueError:
        severity = Severity.MEDIUM
    status = data.get("status", "live")
    if status not in {"live", "killed", "downgraded"}:
        status = "live"
    return Candidate(
        rule_id=data.get("rule_id"),
        location=str(data.get("location", "") or ""),
        function_name=data.get("function_name"),
        severity=severity,
        title=str(data.get("title", "") or ""),
        reason=str(data.get("reason", "") or ""),
        recommendation=str(data.get("recommendation", "") or ""),
        code_snippet=data.get("code_snippet"),
        source=str(data.get("source", "seed") or "seed"),  # type: ignore[arg-type]
        raw=dict(data.get("raw") or {}),
        gate_traces=dict(data.get("gate_traces") or {}),
        status=status,  # type: ignore[arg-type]
        killed_by=data.get("killed_by"),
        killed_reason=data.get("killed_reason"),
    )


# ---------------------------------------------------------------------------
# Finding <-> Candidate conversion
# ---------------------------------------------------------------------------


def finding_to_candidate(f: Finding, *, source: CandidateSource) -> Candidate:
    return Candidate(
        rule_id=f.rule_id,
        location=f.location,
        function_name=None,
        severity=f.severity,
        title=f.title,
        reason=f.description,
        recommendation=f.recommendation,
        code_snippet=f.code_snippet,
        source=source,
        raw={
            "id": f.id,
            "impact": f.impact,
            "confidence": f.confidence,
            "kill_signal": dict(f.kill_signal) if f.kill_signal else None,
        },
    )


def candidate_to_finding(c: Candidate, *, id_prefix: str, idx: int) -> Finding:
    kill_signal_meta: dict[str, Any] = {
        "status": c.status,
        "killed_by": c.killed_by,
        "killed_reason": c.killed_reason,
        "source": c.source,
        "function_name": c.function_name,
        "gate_traces": c.gate_traces,
    }
    # Preserve upstream kill_signal (from _judge_lite provenance) if present.
    upstream = c.raw.get("kill_signal") if isinstance(c.raw, dict) else None
    if isinstance(upstream, dict):
        kill_signal_meta.setdefault("provenance_upstream", upstream)
    return Finding(
        id=f"{id_prefix}-{idx:03d}",
        rule_id=c.rule_id,
        severity=c.severity,
        title=c.title,
        location=c.location,
        description=c.reason,
        impact=c.reason,
        recommendation=c.recommendation,
        code_snippet=c.code_snippet,
        confidence=c.raw.get("confidence") if isinstance(c.raw, dict) else None,
        kill_signal=kill_signal_meta,
    )
