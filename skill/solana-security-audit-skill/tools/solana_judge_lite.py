# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""``solana_judge_lite`` — deterministic L4 post-processor.

Runs three passes over the surviving L4 findings:

1. **Severity floor** — a finding whose ``rule_id`` matches a KB pattern
   never reports below the KB baseline (e.g. ``missing_signer_check`` is
   always ≥ High regardless of how the A1 agent ranked it).
2. **Dedup** — collapse duplicates by ``(rule_id, location, title)``; on
   collision the entry with the **higher** severity wins.
3. **Provenance** — stamp ``kill_signal`` with ``judge="judge-lite"``,
   the source (A1/A2/rule), KB matches, and any ``gate_traces`` carried
   over from the candidate.

No LLM. Returns the retained findings, dropped duplicates, and a
severity histogram.
"""

from __future__ import annotations

from typing import Any

from core.types import Finding, Severity

__all__ = ["SolanaJudgeLiteTool", "execute"]


_RULE_MIN_SEVERITY: dict[str, Severity] = {
    "arbitrary_cpi": Severity.CRITICAL,
    "missing_signer_check": Severity.HIGH,
    "missing_owner_check": Severity.HIGH,
    "account_data_matching": Severity.HIGH,
    "pda_derivation_error": Severity.HIGH,
    "integer_overflow": Severity.MEDIUM,
    "uninitialized_account": Severity.MEDIUM,
    "duplicate_account": Severity.HIGH,
    "closing_account_error": Severity.HIGH,
    "sysvar_spoofing": Severity.MEDIUM,
}


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 5,
    Severity.HIGH: 4,
    Severity.MEDIUM: 3,
    Severity.LOW: 2,
    Severity.INFO: 1,
}


def _uprank(current: Severity, rule_id: str | None) -> Severity:
    if not rule_id:
        return current
    baseline = _RULE_MIN_SEVERITY.get(rule_id)
    if baseline is None:
        return current
    if _SEVERITY_RANK[current] >= _SEVERITY_RANK[baseline]:
        return current
    return baseline


def _as_finding(obj: Any) -> Finding:
    if isinstance(obj, Finding):
        return obj
    if isinstance(obj, dict):
        return Finding.from_dict(obj) if hasattr(Finding, "from_dict") else Finding(**_coerce_finding_dict(obj))
    raise TypeError(f"Cannot coerce {type(obj).__name__} to Finding")


def _coerce_finding_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Best-effort dict → Finding kwargs. Severity must be Severity."""
    sev = d.get("severity")
    if isinstance(sev, str):
        try:
            sev = Severity.from_value(sev)
        except ValueError:
            sev = Severity.MEDIUM
    elif sev is None:
        sev = Severity.MEDIUM
    return {
        "id": d.get("id", ""),
        "rule_id": d.get("rule_id"),
        "severity": sev,
        "title": d.get("title", ""),
        "location": d.get("location", ""),
        "description": d.get("description", ""),
        "impact": d.get("impact", ""),
        "recommendation": d.get("recommendation", ""),
        "code_snippet": d.get("code_snippet"),
        "confidence": d.get("confidence"),
        "kill_signal": d.get("kill_signal"),
    }


def execute(
    findings: list[Any] | None = None,
    kb_patterns: list[dict[str, Any]] | None = None,
    scanner_hints: list[dict[str, Any]] | None = None,
    scanner_status: str = "assisted",
    provenance: str = "ai",
    extra_kill_signal: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness entry point for ``solana_judge_lite``.

    Parameters
    ----------
    findings
        Surviving findings after Gate4. Each may be a :class:`Finding` or
        its ``to_dict()`` form.
    kb_patterns
        ``knowledge/solana_bug_patterns.json["patterns"]``; used to
        populate the ``matched_kb`` / ``kb_patterns`` provenance fields.
    scanner_hints
        Optional scanner hint list (so a finding whose rule matched the
        scanner can be marked ``matched_scanner=true``).
    scanner_status
        Upstream status (``parser_failed`` / ``scanner_failed`` /
        ``zero_hints`` / ``assisted``) — affects confidence floor.
    provenance
        ``"ai" | "scanner"`` — controls default confidence when the
        finding has none.
    extra_kill_signal
        Optional provenance overrides merged into the emitted
        ``kill_signal`` dict (e.g. pipeline name).
    """
    raw_findings = list(findings or [])
    scanner_rules = {
        str(h.get("rule_id"))
        for h in (scanner_hints or [])
        if isinstance(h, dict) and h.get("rule_id")
    }
    kb_ids = [str(p.get("id")) for p in (kb_patterns or []) if isinstance(p, dict) and p.get("id")]
    kb_rules = {
        str(rule)
        for pattern in (kb_patterns or [])
        if isinstance(pattern, dict)
        for rule in pattern.get("rule_ids", []) or []
    }
    # Include top-level KB ids as rule matches too — mirrors run_audit._judge_lite behaviour.
    kb_rules |= {str(pid) for pid in kb_ids}

    judged: list[Finding] = []
    dropped: list[Finding] = []
    seen: dict[tuple[str, str, str], int] = {}

    for obj in raw_findings:
        f = _as_finding(obj)
        f.severity = _uprank(f.severity, f.rule_id)
        matched_scanner = bool(f.rule_id and f.rule_id in scanner_rules)
        matched_kb = bool(f.rule_id and f.rule_id in kb_rules)
        status = "confirmed" if (matched_scanner or matched_kb or provenance == "ai") else "candidate"
        confidence = f.confidence
        if confidence is None:
            confidence = 0.85 if provenance == "ai" else 0.45
        if matched_scanner and matched_kb:
            confidence = max(confidence, 0.92)
        elif matched_scanner or matched_kb:
            confidence = max(confidence, 0.75)
        if scanner_status in {"parser_failed", "scanner_failed", "zero_hints"} and provenance == "ai":
            confidence = min(max(confidence, 0.65), 0.9)
        f.confidence = round(confidence, 2)

        prior = dict(f.kill_signal) if isinstance(f.kill_signal, dict) else {}
        stamped = {
            "judge": "judge-lite",
            "status": status,
            "provenance": provenance,
            "scanner_status": scanner_status,
            "matched_scanner": matched_scanner,
            "matched_kb": matched_kb,
            "kb_patterns": kb_ids,
        }
        if prior:
            stamped["provenance_upstream"] = prior
        if extra_kill_signal:
            stamped.update(extra_kill_signal)
        f.kill_signal = stamped

        key = (f.rule_id or "", f.location or "", f.title)
        if key in seen:
            existing_idx = seen[key]
            existing = judged[existing_idx]
            # Keep the entry with the higher severity; drop the other.
            if _SEVERITY_RANK[f.severity] > _SEVERITY_RANK[existing.severity]:
                dropped.append(existing)
                judged[existing_idx] = f
            else:
                dropped.append(f)
            continue
        seen[key] = len(judged)
        judged.append(f)

    statistics = {
        "critical": sum(1 for f in judged if f.severity is Severity.CRITICAL),
        "high": sum(1 for f in judged if f.severity is Severity.HIGH),
        "medium": sum(1 for f in judged if f.severity is Severity.MEDIUM),
        "low": sum(1 for f in judged if f.severity is Severity.LOW),
        "info": sum(1 for f in judged if f.severity is Severity.INFO),
        "total": len(judged),
    }

    return {
        "findings": [f.to_dict() if hasattr(f, "to_dict") else _finding_to_dict(f) for f in judged],
        "dropped": [f.to_dict() if hasattr(f, "to_dict") else _finding_to_dict(f) for f in dropped],
        "statistics": statistics,
    }


def _finding_to_dict(f: Finding) -> dict[str, Any]:
    """Fallback dict serialiser when Finding has no ``to_dict``."""
    return {
        "id": f.id,
        "rule_id": f.rule_id,
        "severity": f.severity.value if isinstance(f.severity, Severity) else str(f.severity),
        "title": f.title,
        "location": f.location,
        "description": f.description,
        "impact": f.impact,
        "recommendation": f.recommendation,
        "code_snippet": f.code_snippet,
        "confidence": f.confidence,
        "kill_signal": f.kill_signal,
    }


class SolanaJudgeLiteTool:
    """OpenHarness Tool class — thin wrapper."""

    name: str = "solana_judge_lite"
    version: str = "v0.1.0"

    def execute(
        self,
        findings: list[Any] | None = None,
        kb_patterns: list[dict[str, Any]] | None = None,
        scanner_hints: list[dict[str, Any]] | None = None,
        scanner_status: str = "assisted",
        provenance: str = "ai",
        extra_kill_signal: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return execute(
            findings=findings,
            kb_patterns=kb_patterns,
            scanner_hints=scanner_hints,
            scanner_status=scanner_status,
            provenance=provenance,
            extra_kill_signal=extra_kill_signal,
            **kwargs,
        )
