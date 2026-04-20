"""Markdown report generators.

Phase 1 scaffold: writes bare-bones templates so the E2E smoke test in
Phase 2 can compare outputs. Full templates in Phase 2 §P2.5.
"""

from __future__ import annotations

from core.types import ScanResult


def render_risk_summary(result: ScanResult) -> str:
    stats = result.statistics.to_dict()
    return f"""# SolGuard Risk Summary

- **Contract**: `{result.contract_name}`
- **Risk Level**: **{result.risk_level}**
- **Timestamp**: {result.timestamp}

## Severity Overview

| Severity | Count |
|----------|-------|
| Critical | {stats["critical"]} |
| High     | {stats["high"]} |
| Medium   | {stats["medium"]} |
| Low      | {stats["low"]} |
| Info     | {stats["info"]} |
| **Total**| **{stats["total"]}** |

## Top Findings

{_format_top_findings(result)}
"""


def render_assessment(result: ScanResult) -> str:
    body = "\n".join(_format_finding_block(i, f.to_dict()) for i, f in enumerate(result.findings, 1))
    return f"""# SolGuard Contract Security Assessment

- **Contract**: `{result.contract_name}`
- **Path**: `{result.contract_path}`
- **Risk Level**: **{result.risk_level}**
- **Findings**: {len(result.findings)}

---

{body or '_No findings._'}
"""


def render_checklist(result: ScanResult) -> str:
    _ = result
    return """# SolGuard Audit Checklist

> Phase 1 scaffold. The full 15-item checklist ships in Phase 2.

- [ ] Signer checks in place for every `AccountInfo`
- [ ] Owner checks in place for every account
- [ ] PDA seeds align between `find_program_address` and `#[account(seeds = ...)]`
- [ ] All CPI targets are validated
- [ ] Arithmetic uses `checked_*` helpers
- [ ] `#[account(init, payer, space)]` invariants are upheld
- [ ] Account discriminators are validated before deserialization
"""


def _format_top_findings(result: ScanResult) -> str:
    if not result.findings:
        return "_No findings to report._"
    top = result.findings[:5]
    lines = [
        f"- **[{f.severity.value}]** {f.title} — `{f.location}`" for f in top
    ]
    return "\n".join(lines)


def _format_finding_block(index: int, f: dict) -> str:
    return f"""### {index}. [{f['severity']}] {f['title']}

- **Rule**: `{f.get('rule_id') or 'n/a'}`
- **Location**: `{f['location']}`
- **Confidence**: {f.get('confidence') or 'n/a'}

**Description**

{f['description']}

**Impact**

{f['impact']}

**Recommendation**

{f['recommendation']}

---
"""
