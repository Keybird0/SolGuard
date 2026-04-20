"""solana_scan tool — run registered security rules against a parsed contract.

Phase 1 scaffold: bootstraps the registry and wires an empty pipeline.
Concrete rules (missing_signer_check, missing_owner_check, …) will be added
in Phase 2 (see docs/04-SolGuard项目管理/03-Phase2-Skill与工具开发.md §P2.3).
"""

from __future__ import annotations

import logging
from typing import Any

from core.types import Finding, ParsedContract, Statistics

from .rules import RuleRegistry

logger = logging.getLogger(__name__)


def scan(parsed: ParsedContract, code: str, rules: list[str] | None = None) -> dict[str, Any]:
    """Execute all (or a subset of) registered rules against the parsed contract."""
    all_rules = RuleRegistry.all_rules()
    selected = (
        [r for r in all_rules if r.id in rules] if rules else all_rules
    )

    findings: list[Finding] = []
    errors: list[dict[str, str]] = []

    for rule in selected:
        try:
            rule_findings = rule.check(parsed, code)
            findings.extend(rule_findings)
        except Exception as exc:
            logger.exception("rule %s failed", rule.id)
            errors.append({"rule_id": rule.id, "error": str(exc)})

    findings = _deduplicate(findings)
    findings.sort(key=_severity_sort_key)

    stats = Statistics.from_findings(findings)

    return {
        "findings": [f.to_dict() for f in findings],
        "statistics": stats.to_dict(),
        "rules_run": [r.id for r in selected],
        "errors": errors,
    }


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, str]] = set()
    unique: list[Finding] = []
    for f in findings:
        key = (f.rule_id or f.id, f.location)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique


_SEVERITY_ORDER = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
    "Info": 4,
}


def _severity_sort_key(finding: Finding) -> tuple[int, str]:
    return (_SEVERITY_ORDER.get(finding.severity.value, 99), finding.id)


def execute(
    parsed: dict[str, Any] | None = None,
    code: str | None = None,
    rules: list[str] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness Tool entry point."""
    if parsed is None or code is None:
        raise ValueError("both 'parsed' and 'code' are required")
    parsed_contract = ParsedContract.from_dict(parsed)
    return scan(parsed_contract, code, rules=rules)
