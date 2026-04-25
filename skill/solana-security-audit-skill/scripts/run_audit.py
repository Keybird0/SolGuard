#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""In-process SolGuard audit orchestrator (AI-first).

Two execution modes share the same module:

* **Single-fixture mode** — ``run_audit(fixture_path, ...)``. Back-compat
  shim that walks ``solana_parse`` → ``solana_scan`` → ``semgrep_runner``
  → ``ai.analyzer`` → ``solana_report`` against exactly one Rust file.
  Used by ``scripts/e2e_smoke.sh`` / ``scripts/e2e_smoke_degraded.sh``.

* **Multi-target mode** — ``run_audit_multi(inputs, ...)``. New path used
  whenever ``--inputs-json`` is supplied. It runs the *AI-first planner*
  (``ai.planner.plan_audit_targets``) to decide **what** to audit, then
  drives per-target audits where the LLM is the primary decision maker
  and the Phase-2 scanners serve only as evidence providers.

  Per target:

  1. Parse (best-effort; failure recorded as ``scanner_status=parser_failed``).
  2. Scan + Semgrep (best-effort; 0 hints → ``scanner_status=zero_hints``
     but the pipeline does **not** stop).
  3. AI reviewer (``cross_validate_and_explore``) with optional
     ``comparison_files`` pulled from ``recommended`` / ``secure``
     siblings so the model can contrast vulnerable vs patched code.
  4. Normalise severity using a per-rule baseline so known-high rules
     (missing_signer, missing_owner, arbitrary_cpi, …) never surface as
     ``Low`` just because the LLM hedged.

  Findings are aggregated across all targets into a single
  :class:`core.types.ScanResult`, and the rendered Markdown includes
  per-target sections plus a "Targets audited" preamble.

AI-first contract: if **any** scanner step raises or returns empty,
the audit still continues to the AI reviewer. Without an AI key, we
fall back to the deterministic degraded summary exactly like v1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_THIS = Path(__file__).resolve()
_SKILL_ROOT = _THIS.parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from ai.analyzer import AIAnalyzer  # noqa: E402
from ai.planner import build_inventory, plan_audit_targets  # noqa: E402
from core.types import Finding, ScanResult, Severity, Statistics  # noqa: E402
from tools.solana_parse import parse_file  # noqa: E402
from tools.solana_report import persist  # noqa: E402
from tools.semgrep_runner import run as semgrep_run  # noqa: E402
from tools.solana_scan import scan  # noqa: E402

_KB_PATH = _SKILL_ROOT / "knowledge" / "solana_bug_patterns.json"

# Baseline severities used to patch known rule_ids so the LLM's hedging
# doesn't erase a clear High/Critical. Anything not in this table keeps
# the LLM-reported severity.
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


def _emit_stage(stage: str, **fields: Any) -> None:
    """Emit a single-line JSON event so solguard-server can map stages to status."""
    payload: dict[str, Any] = {"stage": stage}
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _ai_available() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def _severity_of(rule_id: str) -> Severity:
    return _RULE_MIN_SEVERITY.get(rule_id, Severity.LOW)


def _uprank_severity(current: Severity, rule_id: str | None) -> Severity:
    """Ensure a known rule never reports below its baseline severity."""
    if not rule_id:
        return current
    baseline = _RULE_MIN_SEVERITY.get(rule_id)
    if baseline is None:
        return current
    if _SEVERITY_RANK[current] >= _SEVERITY_RANK[baseline]:
        return current
    return baseline


# ---------------------------------------------------------------------------
# Finding builders
# ---------------------------------------------------------------------------


def _degraded_reports(
    fixture_name: str,
    scan_hints: list[dict[str, Any]],
    analyzer_error: str | None,
) -> dict[str, str]:
    """Deterministic Markdown used when the LLM is unavailable."""
    header = "# DEGRADED — LLM unavailable\n"
    if analyzer_error:
        header += f"\n> Analyzer error: `{analyzer_error}`\n"
    lines = [
        header,
        f"\n**File**: `{fixture_name}`",
        f"\n**Scan hints**: {len(scan_hints)}\n",
    ]
    if scan_hints:
        lines.append("\n## Unverified scan hints\n")
        for h in scan_hints:
            lines.append(
                f"- `{h.get('rule_id')}` @ `{h.get('location')}` — {h.get('why', '')}"
            )
    body = "\n".join(lines) + "\n"
    return {
        "risk_summary": body,
        "assessment": body + "\n*(Assessment omitted — degraded mode.)*\n",
        "checklist": body + "\n*(Checklist omitted — degraded mode.)*\n",
    }


def _findings_from_ai(
    payload: dict[str, Any],
    *,
    id_prefix: str = "AI",
    target_file: str | None = None,
) -> list[Finding]:
    out: list[Finding] = []
    items = payload.get("confirmed", []) + payload.get("exploratory", [])
    for idx, item in enumerate(items):
        rule_id = item.get("rule_id")
        try:
            severity = Severity.from_value(str(item.get("severity", "Medium")))
        except ValueError:
            severity = Severity.MEDIUM
        severity = _uprank_severity(severity, rule_id)
        location = item.get("location", "")
        # Prepend the target file name to the location when the AI gave a
        # bare "line 22" hint but we know which file we asked about; this
        # keeps findings from multiple targets distinguishable in the UI.
        if target_file and location and ":" not in location:
            location = f"{Path(target_file).name}:{location}"
        out.append(
            Finding(
                id=f"{id_prefix}-{idx:03d}",
                rule_id=rule_id,
                severity=severity,
                title=(rule_id or "finding").replace("_", " ").title(),
                location=location,
                description=item.get("reason", ""),
                impact=item.get("reason", ""),
                recommendation=item.get("recommendation", ""),
                code_snippet=item.get("code_snippet"),
                confidence=0.9,
            )
        )
    return out


def _findings_from_scan(
    scan_hints: list[dict[str, Any]],
    *,
    id_prefix: str = "SCAN",
) -> list[Finding]:
    out: list[Finding] = []
    for idx, h in enumerate(scan_hints):
        rule_id = str(h.get("rule_id", "unknown"))
        severity = _severity_of(rule_id)
        out.append(
            Finding(
                id=f"{id_prefix}-{idx:03d}",
                rule_id=rule_id,
                severity=severity,
                title=rule_id.replace("_", " ").title(),
                location=str(h.get("location", "")),
                description=str(h.get("why", "")),
                impact=str(h.get("why", "")),
                recommendation=(
                    "Review in AI-first mode — this is a low-confidence scan hint."
                ),
                code_snippet=h.get("code_snippet"),
                confidence=0.3,
            )
        )
    return out


def _judge_lite(
    findings: list[Finding],
    *,
    provenance: str,
    scan_result: dict[str, Any],
    kb_patterns: list[dict[str, Any]],
    scanner_status: str,
) -> list[Finding]:
    """Deterministic judge pass: provenance, confidence, severity floor.

    This is intentionally not a second LLM call. It gives the report a
    transparent "why trust this" trail while keeping the hackathon path cheap
    and stable.
    """
    scanner_rules = {str(h.get("rule_id")) for h in scan_result.get("hints", [])}
    kb_ids = [str(p.get("id")) for p in kb_patterns if p.get("id")]
    kb_rules = {
        str(rule)
        for pattern in kb_patterns
        for rule in pattern.get("rule_ids", [])
    }
    judged: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        finding.severity = _uprank_severity(finding.severity, finding.rule_id)
        matched_scanner = bool(finding.rule_id and finding.rule_id in scanner_rules)
        matched_kb = bool(finding.rule_id and finding.rule_id in kb_rules)
        status = "confirmed" if (matched_scanner or matched_kb or provenance == "ai") else "candidate"
        confidence = finding.confidence
        if confidence is None:
            confidence = 0.85 if provenance == "ai" else 0.45
        if matched_scanner and matched_kb:
            confidence = max(confidence, 0.92)
        elif matched_scanner or matched_kb:
            confidence = max(confidence, 0.75)
        if scanner_status in {"parser_failed", "scanner_failed", "zero_hints"} and provenance == "ai":
            confidence = min(max(confidence, 0.65), 0.9)
        finding.confidence = round(confidence, 2)
        finding.kill_signal = {
            "judge": "judge-lite",
            "status": status,
            "provenance": provenance,
            "scanner_status": scanner_status,
            "matched_scanner": matched_scanner,
            "matched_kb": matched_kb,
            "kb_patterns": kb_ids,
        }
        key = (finding.rule_id or "", finding.location or "", finding.title)
        if key in seen:
            continue
        seen.add(key)
        judged.append(finding)
    return judged


def _risk_level(findings: list[Finding]) -> str:
    order = [
        Severity.CRITICAL,
        Severity.HIGH,
        Severity.MEDIUM,
        Severity.LOW,
        Severity.INFO,
    ]
    for sev in order:
        if any(f.severity is sev for f in findings):
            return sev.value
    return Severity.INFO.value


# ---------------------------------------------------------------------------
# Per-target evidence gathering (best-effort)
# ---------------------------------------------------------------------------


def _safe_parse(fixture_path: Path) -> tuple[Any, str | None]:
    try:
        pc = parse_file(fixture_path)
        if pc.parse_error:
            return pc, pc.parse_error
        return pc, None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _safe_scan(pc: Any) -> tuple[dict[str, Any], str | None]:
    if pc is None:
        return {"hints": [], "scan_errors": [], "statistics": {"total": 0}}, "no parsed contract"
    try:
        return scan(pc), None
    except Exception as exc:  # noqa: BLE001
        return (
            {"hints": [], "scan_errors": [], "statistics": {"total": 0}},
            f"{type(exc).__name__}: {exc}",
        )


def _safe_semgrep(fixture_path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        return semgrep_run(target_path=fixture_path), None
    except Exception as exc:  # noqa: BLE001
        return {"results": [], "tool_error": str(exc)}, f"{type(exc).__name__}: {exc}"


def _read_snippet(path: str, max_bytes: int = 12_000) -> str:
    try:
        data = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if len(data.encode("utf-8")) <= max_bytes:
        return data
    return data[: max_bytes - 80] + "\n// ... truncated ..."


def _line_for_offset(source: str, offset: int) -> int:
    return source.count("\n", 0, max(offset, 0)) + 1


def _line_excerpt(source: str, line: int, radius: int = 1) -> str:
    lines = source.splitlines()
    start = max(line - 1 - radius, 0)
    end = min(line + radius, len(lines))
    return "\n".join(lines[start:end])


def _load_kb_patterns() -> list[dict[str, Any]]:
    try:
        raw = json.loads(_KB_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict):
        patterns = raw.get("patterns", [])
    else:
        patterns = raw
    return [p for p in patterns if isinstance(p, dict)]


def _compact_function(fn: dict[str, Any], source: str) -> dict[str, Any]:
    name = str(fn.get("name", ""))
    line = int(fn.get("line") or 0)
    body = _line_excerpt(source, line, radius=3) if line else ""
    return {
        "name": name,
        "line": line,
        "is_pub": bool(fn.get("is_pub")),
        "args": fn.get("args", ""),
        "return_type": fn.get("return_type") or fn.get("ret") or "",
        "signals": {
            "has_require": "require!" in body or "require_keys_" in body,
            "has_invoke": "invoke(" in body or "invoke_signed(" in body,
            "has_mut_borrow": "borrow_mut" in body or "try_borrow_mut" in body,
        },
    }


def _source_signal_matches(source: str) -> list[dict[str, Any]]:
    patterns: list[tuple[str, str]] = [
        ("invoke", r"\binvoke\s*\("),
        ("invoke_signed", r"\binvoke_signed\s*\("),
        ("spl_token_instruction", r"spl_token::instruction::[A-Za-z_]+\s*\("),
        ("create_program_address", r"Pubkey::create_program_address\s*\("),
        ("find_program_address", r"Pubkey::find_program_address\s*\("),
        ("try_borrow_mut_data", r"try_borrow_mut_data\s*\("),
        ("manual_deserialize", r"try_from_slice|deserialize|unpack_unchecked"),
        ("manual_lamports", r"\.lamports\s*\(|try_borrow_mut_lamports"),
        ("require_keys_eq", r"require_keys_eq!\s*\("),
        ("require_keys_neq", r"require_keys_neq!\s*\("),
        ("account_close", r"\bclose\s*\(|CLOSED_ACCOUNT_DISCRIMINATOR|assign\s*\("),
    ]
    matches: list[dict[str, Any]] = []
    for label, regex in patterns:
        for match in re.finditer(regex, source):
            line = _line_for_offset(source, match.start())
            matches.append(
                {
                    "kind": label,
                    "line": line,
                    "snippet": _line_excerpt(source, line, radius=0).strip(),
                }
            )
            if len(matches) >= 40:
                return matches
    return matches


def _build_evidence_pack_v2(
    *,
    pc: Any,
    source_code: str,
    target: dict[str, Any],
    scan_result: dict[str, Any],
    semgrep_raw: dict[str, Any],
    scanner_status: str,
    parser_error: str | None,
    scan_error: str | None,
) -> dict[str, Any]:
    """Small, structured context block that tells the LLM where to look.

    This deliberately summarizes structure instead of appending more raw source,
    matching the PDF's "feed more precisely, not more text" guidance.
    """
    parse_dict = pc.to_dict() if pc is not None else {}
    source = source_code or parse_dict.get("source_code", "")
    accounts = []
    for account in parse_dict.get("accounts", [])[:12]:
        fields = []
        for field in account.get("fields", [])[:20]:
            fields.append(
                {
                    "name": field.get("name"),
                    "type_category": field.get("type_category"),
                    "ty": field.get("ty"),
                    "is_pub": field.get("is_pub"),
                    "attrs": field.get("attrs", []),
                    "line": field.get("line"),
                }
            )
        accounts.append({"name": account.get("name"), "line": account.get("line"), "fields": fields})

    source_signals = _source_signal_matches(source)
    semgrep_results = semgrep_raw.get("results", []) if isinstance(semgrep_raw, dict) else []
    return {
        "version": "evidence-pack-v2.2026-04-25",
        "target": {
            "file": target.get("file"),
            "role": target.get("role"),
            "lesson": target.get("lesson"),
            "priority": target.get("priority"),
            "expectedBugClasses": target.get("expectedBugClasses") or [],
        },
        "structure": {
            "program": parse_dict.get("metadata", {}).get("program_module"),
            "declare_id": parse_dict.get("metadata", {}).get("declare_id"),
            "functions": [
                _compact_function(fn, source)
                for fn in parse_dict.get("functions", [])[:20]
            ],
            "instructions": parse_dict.get("instructions", [])[:20],
            "accounts": accounts,
            "anchor_attrs": parse_dict.get("anchor_attrs", [])[:30],
        },
        "source_signals": source_signals,
        "external_interactions": [
            item for item in source_signals if item["kind"] in {"invoke", "invoke_signed", "spl_token_instruction"}
        ],
        "state_access": [
            item for item in source_signals if item["kind"] in {"try_borrow_mut_data", "manual_deserialize", "manual_lamports"}
        ],
        "scanner": {
            "status": scanner_status,
            "hint_count": len(scan_result.get("hints", [])),
            "rules": sorted({str(h.get("rule_id")) for h in scan_result.get("hints", [])}),
            "parser_error": parser_error,
            "scan_error": scan_error,
        },
        "semgrep": {
            "result_count": len(semgrep_results),
            "checks": sorted(
                {
                    str(r.get("check_id", ""))
                    for r in semgrep_results[:20]
                    if isinstance(r, dict)
                }
            ),
        },
    }


def _route_kb_patterns(
    *,
    target: dict[str, Any],
    scan_result: dict[str, Any],
    evidence_pack: dict[str, Any],
    source_code: str,
) -> list[dict[str, Any]]:
    """Deterministic KB Lite routing.

    No vector store yet: for hackathon reliability, route by expected bug
    classes, scanner rule ids, and high-signal source regexes.
    """
    expected = {str(x) for x in (target.get("expectedBugClasses") or [])}
    rule_ids = {str(h.get("rule_id")) for h in scan_result.get("hints", [])}
    signal_kinds = {str(s.get("kind")) for s in evidence_pack.get("source_signals", [])}
    routed: list[dict[str, Any]] = []
    for pattern in _load_kb_patterns():
        aliases = set(str(x) for x in pattern.get("aliases", []))
        rules = set(str(x) for x in pattern.get("rule_ids", []))
        signals = set(str(x) for x in pattern.get("source_signals", []))
        regexes = [str(x) for x in pattern.get("source_regex", [])]
        reasons: list[str] = []
        if expected & aliases:
            reasons.append("expected_bug_class")
        if rule_ids & rules:
            reasons.append("scanner_rule")
        if signal_kinds & signals:
            reasons.append("source_signal")
        if any(re.search(rx, source_code, flags=re.MULTILINE) for rx in regexes):
            reasons.append("source_regex")
        if reasons:
            picked = {
                "id": pattern.get("id"),
                "title": pattern.get("title"),
                "severity": pattern.get("severity"),
                "rule_ids": pattern.get("rule_ids", []),
                "why_it_matters": pattern.get("why_it_matters", ""),
                "look_for": pattern.get("look_for", []),
                "fix": pattern.get("fix", ""),
                "route_reasons": sorted(set(reasons)),
            }
            routed.append(picked)
    return routed[:8]


def _build_target_context(
    target: dict[str, Any],
    scanner_status: str,
    parser_error: str | None,
    scan_error: str | None,
    evidence_pack: dict[str, Any] | None = None,
    kb_patterns: list[dict[str, Any]] | None = None,
) -> str:
    """Assemble the AI-first extra context block for one target.

    The block is appended to the standard audit prompt and tells the LLM
    three things the schema examples can't: which files to contrast,
    which bug classes the curator expects, and whether scanner evidence
    is trustworthy.
    """
    parts: list[str] = []
    parts.append("\n## target_metadata")
    parts.append("```json")
    parts.append(
        json.dumps(
            {
                "role": target.get("role"),
                "priority": target.get("priority"),
                "lesson": target.get("lesson"),
                "expectedBugClasses": target.get("expectedBugClasses") or [],
                "scanner_status": scanner_status,
                "parser_error": parser_error,
                "scan_error": scan_error,
            },
            ensure_ascii=False,
        )
    )
    parts.append("```")
    if evidence_pack:
        parts.append("\n## evidence_pack_v2")
        parts.append("```json")
        parts.append(json.dumps(evidence_pack, ensure_ascii=False)[:16_000])
        parts.append("```")
    if kb_patterns:
        parts.append("\n## solana_kb_lite_routed_patterns")
        parts.append("```json")
        parts.append(json.dumps(kb_patterns, ensure_ascii=False)[:8_000])
        parts.append("```")
        parts.append(
            "\nUse these routed bug patterns as verified domain guidance, "
            "not as automatic findings. Confirm each issue against the target source."
        )
    comparisons = target.get("comparisonFiles") or []
    if comparisons:
        parts.append("\n## comparison_sources (patched/safe variants for contrast)")
        for comp in comparisons[:2]:
            parts.append(f"\n### {Path(comp).name} ({comp})")
            parts.append("```rust")
            parts.append(_read_snippet(comp, max_bytes=6_000))
            parts.append("```")
    if scanner_status in ("parser_failed", "scanner_failed", "zero_hints"):
        parts.append(
            "\n**Note**: scanner evidence is degraded (see `scanner_status`). "
            "You are the primary reviewer — do not limit findings to scanner "
            "hints; re-read the source and surface real exploitable issues."
        )
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _render_markdown(
    title: str,
    fixture: str,
    findings: list[Finding],
    include_body: bool = False,
) -> str:
    head = f"# {title} — {fixture}\n\n"
    head += f"- Findings: {len(findings)}\n"
    if findings:
        head += f"- Top severity: {findings[0].severity.value}\n"
    head += "\n## Findings\n\n"
    for f in findings:
        head += f"### [{f.severity.value}] {f.title}\n"
        head += f"- **Location**: `{f.location}`\n"
        head += f"- **Rule**: `{f.rule_id}`\n"
        head += f"- **Reason**: {f.description}\n"
        head += f"- **Recommendation**: {f.recommendation}\n"
        if include_body and f.code_snippet:
            head += f"\n```rust\n{f.code_snippet}\n```\n"
        head += "\n"
    return head


def _render_checklist(fixture: str, findings: list[Finding]) -> str:
    lines = [f"# Checklist — {fixture}\n"]
    if not findings:
        lines.append("- [x] No exploitable issues detected.\n")
    else:
        for f in findings:
            lines.append(f"- [ ] ({f.severity.value}) {f.title} @ `{f.location}`")
    return "\n".join(lines) + "\n"


def _render_multi_target_markdown(
    title: str,
    findings: list[Finding],
    target_summaries: list[dict[str, Any]],
    include_body: bool = False,
    plan: dict[str, Any] | None = None,
    benchmark_summary: dict[str, Any] | None = None,
) -> str:
    head = f"# {title}\n\n"
    head += f"- Targets audited: {len(target_summaries)}\n"
    head += f"- Findings: {len(findings)}\n"
    if findings:
        top = sorted(findings, key=lambda f: _SEVERITY_RANK[f.severity], reverse=True)[0]
        head += f"- Top severity: {top.severity.value}\n"
    head += "\n## Targets audited\n\n"
    for summary in target_summaries:
        badge = summary.get("scanner_status", "assisted")
        head += (
            f"- `{summary.get('file_name', 'unknown')}` "
            f"[{summary.get('role', '?')}] · scanner={badge} · "
            f"ai={summary.get('ai_status', '?')} · findings={summary.get('findings', 0)}\n"
        )
    head += "\n## Why trust this result?\n\n"
    head += (
        "- **Target selection**: AI-first planner selected auditable targets before scanning"
        f" (mode=`{(plan or {}).get('mode', 'unknown')}`).\n"
    )
    scanner_counts: dict[str, int] = {}
    provenance_counts: dict[str, int] = {}
    kb_ids: set[str] = set()
    for summary in target_summaries:
        scanner_counts[str(summary.get("scanner_status"))] = scanner_counts.get(str(summary.get("scanner_status")), 0) + 1
        provenance_counts[str(summary.get("provenance"))] = provenance_counts.get(str(summary.get("provenance")), 0) + 1
        kb_ids.update(str(x) for x in summary.get("kb_patterns", []) if x)
    head += f"- **Evidence provenance**: scanner statuses `{scanner_counts}`, finding provenance `{provenance_counts}`.\n"
    head += (
        "- **Knowledge routing**: "
        + (", ".join(sorted(kb_ids)) if kb_ids else "no KB pattern routed")
        + ".\n"
    )
    head += (
        "- **Judge Lite**: findings are deduplicated, severity-floored by known Solana rule baselines, "
        "and annotated with scanner/KB provenance in `report.json`.\n"
    )
    if benchmark_summary:
        head += "\n## Benchmark summary\n\n"
        head += f"- Expected classes: {', '.join(benchmark_summary.get('expected_classes', []))}\n"
        head += f"- Covered classes: {', '.join(benchmark_summary.get('covered_classes', []))}\n"
        head += f"- Missing classes: {', '.join(benchmark_summary.get('missing_classes', [])) or 'none'}\n"
        head += f"- Coverage: {benchmark_summary.get('coverage_ratio', 0):.0%}\n"
    head += "\n## Findings\n\n"
    if not findings:
        head += "_No exploitable issues surfaced across the audited targets._\n"
    for f in findings:
        head += f"### [{f.severity.value}] {f.title}\n"
        head += f"- **Location**: `{f.location}`\n"
        head += f"- **Rule**: `{f.rule_id}`\n"
        head += f"- **Reason**: {f.description}\n"
        head += f"- **Recommendation**: {f.recommendation}\n"
        if include_body and f.code_snippet:
            head += f"\n```rust\n{f.code_snippet}\n```\n"
        head += "\n"
    return head


def _render_multi_target_checklist(
    findings: list[Finding],
    target_summaries: list[dict[str, Any]],
) -> str:
    lines = [f"# Checklist — {len(target_summaries)} target(s)\n"]
    if not findings:
        lines.append("- [x] No exploitable issues detected across audited targets.\n")
        return "\n".join(lines) + "\n"
    for f in findings:
        lines.append(f"- [ ] ({f.severity.value}) {f.title} @ `{f.location}`")
    return "\n".join(lines) + "\n"


_SEALEVEL_EXPECTED_CLASSES: dict[str, set[str]] = {
    "missing_signer_check": {"missing_signer_check"},
    "account_data_matching": {"account_data_matching"},
    "missing_owner_check": {"missing_owner_check"},
    "arbitrary_cpi": {"arbitrary_cpi"},
    "pda_derivation_error": {"pda_derivation_error"},
    "uninitialized_account": {"uninitialized_account"},
    "closing_account_error": {"closing_account_error", "custom:closing_account_error"},
    "sysvar_spoofing": {"sysvar_spoofing", "custom:sysvar_spoofing"},
    "duplicate_mutable_accounts": {"duplicate_account", "custom:duplicate_mutable_accounts"},
}


def _benchmark_summary(
    plan: dict[str, Any],
    findings: list[Finding],
    per_target: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if plan.get("mode") != "benchmark_repo":
        return None
    observed = {str(f.rule_id) for f in findings if f.rule_id}
    covered: list[str] = []
    missing: list[str] = []
    for expected, aliases in _SEALEVEL_EXPECTED_CLASSES.items():
        if observed & aliases:
            covered.append(expected)
        else:
            missing.append(expected)
    total = len(_SEALEVEL_EXPECTED_CLASSES)
    return {
        "benchmark": "sealevel-attacks-like",
        "expected_classes": sorted(_SEALEVEL_EXPECTED_CLASSES),
        "covered_classes": sorted(covered),
        "missing_classes": sorted(missing),
        "coverage_ratio": len(covered) / total if total else 0.0,
        "targets": len(per_target),
        "findings": len(findings),
        "scanner_statuses": {
            status: sum(1 for item in per_target if item.get("scanner_status") == status)
            for status in sorted({str(item.get("scanner_status")) for item in per_target})
        },
    }


# ---------------------------------------------------------------------------
# Single-fixture (legacy) mode
# ---------------------------------------------------------------------------


def run_audit(
    fixture_path: Path,
    output_root: Path,
    task_id: str,
    force_degraded: bool = False,
    emit_events: bool = False,
) -> dict[str, Any]:
    """Legacy single-file audit path. Kept for e2e_smoke.sh / unit tests."""
    if emit_events:
        _emit_stage("parse", file=str(fixture_path))
    pc, parse_err = _safe_parse(fixture_path)
    if emit_events:
        _emit_stage("scan")
    scan_result, scan_err = _safe_scan(pc)
    if emit_events:
        _emit_stage("semgrep")
    semgrep, _semgrep_err = _safe_semgrep(fixture_path)

    provider = None if force_degraded else _ai_available()
    ai_payload: dict[str, Any]
    if provider is None:
        if emit_events:
            _emit_stage("ai_analyze", status="skipped", reason="no LLM provider configured")
        ai_payload = {
            "confirmed": [],
            "exploratory": [],
            "rejected": [],
            "error": "no LLM provider configured (degraded mode)",
            "unverified_scan_hints": scan_result["hints"],
        }
    else:
        if emit_events:
            _emit_stage("ai_analyze", provider=provider)
        analyzer = AIAnalyzer(provider=provider)
        ai_payload = analyzer.cross_validate_and_explore(
            parse_result=pc.to_dict() if pc is not None else {"parse_error": parse_err},
            scan_hints=scan_result["hints"],
            semgrep_raw=semgrep,
            source_code=pc.source_code if pc is not None else _read_snippet(str(fixture_path)),
            file_path=fixture_path.name,
        )

    analyzer_error = ai_payload.get("error") or ai_payload.get("parse_error")
    degraded = bool(analyzer_error) or provider is None

    if degraded:
        markdown = _degraded_reports(
            fixture_name=fixture_path.name,
            scan_hints=scan_result["hints"],
            analyzer_error=analyzer_error,
        )
        findings = _findings_from_scan(scan_result["hints"])
    else:
        findings = _findings_from_ai(ai_payload, target_file=str(fixture_path))
        if not findings:
            findings = _findings_from_scan(scan_result["hints"])
        markdown = {
            "risk_summary": _render_markdown(
                "Risk Summary", fixture_path.name, findings
            ),
            "assessment": _render_markdown(
                "Assessment", fixture_path.name, findings, include_body=True
            ),
            "checklist": _render_checklist(fixture_path.name, findings),
        }

    sr = ScanResult(
        contract_name=fixture_path.stem,
        contract_path=str(fixture_path),
        risk_level=_risk_level(findings),
        findings=findings,
        statistics=Statistics.from_findings(findings),
        inputs_summary=(
            f"scan_hints={len(scan_result['hints'])} semgrep_hits="
            f"{len(semgrep.get('results', []))} ai_provider={provider or 'none'}"
        ),
        decision="degraded" if degraded else "proceed",
    )

    if emit_events:
        _emit_stage("report")
    bundle = persist(
        task_id=task_id,
        scan_result=sr,
        ai_markdown=markdown,
        output_root=output_root,
    )
    bundle["ai"] = {
        "provider": provider,
        "error": ai_payload.get("error"),
        "parse_error": ai_payload.get("parse_error"),
        "token_usage": ai_payload.get("token_usage"),
    }
    bundle["scan"] = scan_result
    bundle["semgrep"] = {
        "tool_error": semgrep.get("tool_error"),
        "result_count": len(semgrep.get("results", [])),
    }
    if parse_err:
        bundle.setdefault("warnings", []).append(f"parse: {parse_err}")
    if scan_err:
        bundle.setdefault("warnings", []).append(f"scan: {scan_err}")
    return bundle


# ---------------------------------------------------------------------------
# Multi-target (AI-first) mode
# ---------------------------------------------------------------------------


def _audit_one_target(
    target: dict[str, Any],
    provider: str | None,
    emit_events: bool,
    force_degraded: bool,
    id_offset: int,
) -> dict[str, Any]:
    """Run parse+scan+AI for a single target. Always returns a summary dict,
    even when every step failed.
    """
    file_str = target.get("file")
    if not file_str:
        return {
            "target": target,
            "findings": [],
            "scanner_status": "no_file",
            "ai_status": "skipped",
            "error": "target missing 'file'",
        }
    target_path = Path(file_str)
    if not target_path.exists():
        return {
            "target": target,
            "findings": [],
            "scanner_status": "no_file",
            "ai_status": "skipped",
            "error": f"file not found: {file_str}",
        }

    if emit_events:
        _emit_stage("parse", file=file_str)
    pc, parse_err = _safe_parse(target_path)
    scanner_status = "assisted"
    scan_error: str | None = None
    if parse_err:
        scan_result = {"hints": [], "scan_errors": [], "statistics": {"total": 0}}
        scanner_status = "parser_failed"
    else:
        if emit_events:
            _emit_stage("scan")
        scan_result, scan_error = _safe_scan(pc)
        if scan_error:
            scanner_status = "scanner_failed"
        elif not scan_result.get("hints"):
            scanner_status = "zero_hints"

    if emit_events:
        _emit_stage("semgrep")
    semgrep, _semgrep_err = _safe_semgrep(target_path)
    source_code = pc.source_code if pc is not None else _read_snippet(str(target_path))
    evidence_pack = _build_evidence_pack_v2(
        pc=pc,
        source_code=source_code,
        target=target,
        scan_result=scan_result,
        semgrep_raw=semgrep,
        scanner_status=scanner_status,
        parser_error=parse_err,
        scan_error=scan_error,
    )
    kb_patterns = _route_kb_patterns(
        target=target,
        scan_result=scan_result,
        evidence_pack=evidence_pack,
        source_code=source_code,
    )

    ai_status = "skipped"
    ai_payload: dict[str, Any] = {"confirmed": [], "exploratory": [], "rejected": []}
    if force_degraded or provider is None:
        ai_status = "skipped_no_key" if provider is None else "skipped_forced_degraded"
        ai_payload["error"] = "no LLM provider configured (degraded mode)"
    else:
        if emit_events:
            _emit_stage("ai_analyze", provider=provider, file=file_str)
        analyzer = AIAnalyzer(provider=provider)
        extra = _build_target_context(
            target,
            scanner_status,
            parse_err,
            scan_error,
            evidence_pack=evidence_pack,
            kb_patterns=kb_patterns,
        )
        parse_dict = (
            pc.to_dict()
            if pc is not None
            else {"parse_error": parse_err or "unparsed"}
        )
        try:
            ai_payload = analyzer.cross_validate_and_explore(
                parse_result=parse_dict,
                scan_hints=scan_result["hints"],
                semgrep_raw=semgrep,
                source_code=source_code,
                file_path=target_path.name,
                extra_context=extra,
            )
            ai_status = "completed"
            if ai_payload.get("error"):
                ai_status = "errored"
            elif ai_payload.get("parse_error"):
                ai_status = "parse_error"
        except Exception as exc:  # noqa: BLE001
            ai_payload = {
                "confirmed": [],
                "exploratory": [],
                "rejected": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
            ai_status = "errored"

    # Build findings. Prefer AI findings; fall back to scan hints so the
    # report still has something when AI is off or disagreed.
    ai_findings = _findings_from_ai(
        ai_payload,
        id_prefix=f"AI{id_offset:02d}",
        target_file=file_str,
    )
    if ai_findings:
        provenance = "ai"
        findings = _judge_lite(
            ai_findings,
            provenance=provenance,
            scan_result=scan_result,
            kb_patterns=kb_patterns,
            scanner_status=scanner_status,
        )
    elif scan_result.get("hints"):
        provenance = "scanner"
        findings = _judge_lite(
            _findings_from_scan(
                scan_result["hints"], id_prefix=f"SCAN{id_offset:02d}"
            ),
            provenance=provenance,
            scan_result=scan_result,
            kb_patterns=kb_patterns,
            scanner_status=scanner_status,
        )
    else:
        findings = []
        provenance = "none"

    return {
        "target": target,
        "findings": findings,
        "scanner_status": scanner_status,
        "ai_status": ai_status,
        "ai_error": ai_payload.get("error"),
        "ai_parse_error": ai_payload.get("parse_error"),
        "token_usage": ai_payload.get("token_usage"),
        "provenance": provenance,
        "scan_hint_count": len(scan_result.get("hints", [])),
        "file": file_str,
        "evidence_pack": evidence_pack,
        "kb_patterns": kb_patterns,
    }


def run_audit_multi(
    inputs: list[dict[str, Any]],
    output_root: Path,
    task_id: str,
    force_degraded: bool = False,
    emit_events: bool = False,
) -> dict[str, Any]:
    """AI-first entrypoint: plan targets → audit each → aggregate."""
    if emit_events:
        _emit_stage("plan", task_id=task_id)
    inventory = build_inventory(inputs)
    provider = None if force_degraded else _ai_available()
    plan = plan_audit_targets(inputs, provider=provider, inventory=inventory)
    targets: list[dict[str, Any]] = plan.get("targets", [])

    if not targets:
        # Nothing to audit — emit a clear degraded bundle so the server
        # still renders something for the user.
        fake = Path(task_id)
        sr = ScanResult(
            contract_name=task_id,
            contract_path="<no targets>",
            risk_level=Severity.INFO.value,
            findings=[],
            statistics=Statistics.from_findings([]),
            inputs_summary=f"mode={plan.get('mode')} totalRustFiles={inventory.get('totalRustFiles')}",
            decision="degraded",
        )
        md = {
            "risk_summary": (
                f"# Risk Summary\n\nNo auditable Rust sources were found. "
                f"Inventory reports {inventory.get('totalRustFiles', 0)} files; "
                f"planner mode = `{plan.get('mode')}`.\n"
            ),
            "assessment": "# Assessment\n\nNothing to audit.\n",
            "checklist": "# Checklist\n\n- [x] No targets.\n",
        }
        if emit_events:
            _emit_stage("report")
        bundle = persist(task_id=task_id, scan_result=sr, ai_markdown=md, output_root=output_root)
        bundle["plan"] = plan
        bundle["inventory"] = {
            "entries": len(inventory.get("entries", [])),
            "totalRustFiles": inventory.get("totalRustFiles", 0),
        }
        return bundle

    per_target: list[dict[str, Any]] = []
    for idx, target in enumerate(targets):
        summary = _audit_one_target(
            target=target,
            provider=provider,
            emit_events=emit_events,
            force_degraded=force_degraded,
            id_offset=idx,
        )
        per_target.append(summary)

    # Aggregate findings, dedup on (rule_id, location) to avoid AI echoing
    # the same issue across sibling samples.
    agg: list[Finding] = []
    seen_keys: set[tuple[str, str]] = set()
    for summary in per_target:
        for f in summary["findings"]:
            key = (f.rule_id or "", f.location or "")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            agg.append(f)

    # Sort by severity for readability.
    agg.sort(key=lambda f: _SEVERITY_RANK[f.severity], reverse=True)

    target_summaries: list[dict[str, Any]] = [
        {
            "file_name": Path(s["file"]).name if s.get("file") else "?",
            "role": s["target"].get("role"),
            "scanner_status": s.get("scanner_status"),
            "ai_status": s.get("ai_status"),
            "findings": len(s.get("findings", [])),
            "provenance": s.get("provenance"),
            "kb_patterns": [
                str(p.get("id"))
                for p in s.get("kb_patterns", [])
                if p.get("id")
            ],
            "evidence_version": (
                s.get("evidence_pack", {}).get("version")
                if isinstance(s.get("evidence_pack"), dict)
                else None
            ),
        }
        for s in per_target
    ]

    # Decision: degraded when every AI step was skipped/errored.
    any_ai_completed = any(s.get("ai_status") == "completed" for s in per_target)
    decision = "proceed" if any_ai_completed else "degraded"

    first_contract = per_target[0]["file"] if per_target else task_id
    sr = ScanResult(
        contract_name=Path(first_contract).stem if first_contract else task_id,
        contract_path=first_contract or "<multi>",
        risk_level=_risk_level(agg),
        findings=agg,
        statistics=Statistics.from_findings(agg),
        inputs_summary=(
            f"mode={plan.get('mode')} targets={len(targets)} "
            f"provider={provider or 'none'} "
            f"scanner_zero_hint_count={sum(1 for s in per_target if s.get('scanner_status') == 'zero_hints')}"
        ),
        decision=decision,
    )

    title = (
        f"Audit Report — {plan.get('mode')} · {len(targets)} target(s)"
    )
    bench = _benchmark_summary(plan, agg, per_target)
    markdown = {
        "risk_summary": _render_multi_target_markdown(
            title="Risk Summary — " + title,
            findings=agg,
            target_summaries=target_summaries,
            plan=plan,
            benchmark_summary=bench,
        ),
        "assessment": _render_multi_target_markdown(
            title="Assessment — " + title,
            findings=agg,
            target_summaries=target_summaries,
            include_body=True,
            plan=plan,
            benchmark_summary=bench,
        ),
        "checklist": _render_multi_target_checklist(
            findings=agg, target_summaries=target_summaries
        ),
    }

    if emit_events:
        _emit_stage("report")
    bundle = persist(
        task_id=task_id,
        scan_result=sr,
        ai_markdown=markdown,
        output_root=output_root,
    )
    bundle["ai"] = {
        "provider": provider,
        "decision": decision,
        "target_count": len(targets),
    }
    bundle["plan"] = plan
    bundle["inventory"] = {
        "entries": len(inventory.get("entries", [])),
        "totalRustFiles": inventory.get("totalRustFiles", 0),
    }
    bundle["targets"] = [
        {
            "file": s.get("file"),
            "role": s["target"].get("role"),
            "lesson": s["target"].get("lesson"),
            "scanner_status": s.get("scanner_status"),
            "ai_status": s.get("ai_status"),
            "findings": len(s.get("findings", [])),
            "provenance": s.get("provenance"),
            "kb_patterns": [
                p.get("id")
                for p in s.get("kb_patterns", [])
                if p.get("id")
            ],
            "evidence_pack": {
                "version": s.get("evidence_pack", {}).get("version"),
                "source_signals": len(s.get("evidence_pack", {}).get("source_signals", [])),
                "external_interactions": len(s.get("evidence_pack", {}).get("external_interactions", [])),
                "state_access": len(s.get("evidence_pack", {}).get("state_access", [])),
            },
        }
        for s in per_target
    ]
    if bench is not None:
        bundle["benchmark_summary"] = bench
        try:
            out_dir = Path(bundle["output_dir"])
            (out_dir / "benchmark_summary.json").write_text(
                json.dumps(bench, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            lines = [
                "# Sealevel Benchmark Summary\n",
                f"- Targets: {bench['targets']}",
                f"- Findings: {bench['findings']}",
                f"- Coverage: {bench['coverage_ratio']:.0%}",
                f"- Covered: {', '.join(bench['covered_classes'])}",
                f"- Missing: {', '.join(bench['missing_classes']) or 'none'}",
            ]
            (out_dir / "benchmark_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass
    return bundle


# ---------------------------------------------------------------------------
# Input-JSON helpers (unchanged contract with solguard-server)
# ---------------------------------------------------------------------------


def _resolve_primary_rust_file(inputs: list[dict[str, Any]]) -> Path | None:
    """Back-compat: pick exactly one rust_source file for the legacy path."""
    for entry in inputs:
        if entry.get("kind") != "rust_source":
            continue
        primary = entry.get("primaryFile")
        if primary and Path(primary).is_file():
            return Path(primary)
        root = entry.get("rootDir")
        if not root:
            continue
        root_path = Path(root)
        if not root_path.exists():
            continue
        for candidate in root_path.rglob("programs/*/src/lib.rs"):
            if "target" in candidate.parts:
                continue
            return candidate
        for candidate in sorted(root_path.rglob("*.rs")):
            parts = set(candidate.parts)
            if parts & {"target", "tests"}:
                continue
            return candidate
    return None


def _post_callback(
    url: str,
    token: str | None,
    task_id: str,
    bundle: dict[str, Any] | None,
    error: str | None = None,
) -> None:
    """POST the final result back to solguard-server/:taskId/complete."""
    if error is not None or bundle is None:
        body: dict[str, Any] = {
            "status": "failed",
            "error": error or "audit failed without producing a bundle",
        }
    else:
        scan_result = bundle.get("scan_result", {})
        stats = scan_result.get("statistics", {})
        findings_raw = scan_result.get("findings", [])
        findings_out: list[dict[str, Any]] = []
        for idx, f in enumerate(findings_raw):
            findings_out.append({
                "id": f.get("id", f"F-{idx:03d}"),
                "ruleId": f.get("rule_id"),
                "severity": f.get("severity", "Medium"),
                "title": f.get("title", "finding"),
                "location": f.get("location", ""),
                "description": f.get("description", ""),
                "impact": f.get("impact", ""),
                "recommendation": f.get("recommendation", ""),
                "codeSnippet": f.get("code_snippet"),
                "confidence": f.get("confidence"),
            })
        report_block = bundle.get("report") or {}
        report_md_path = (
            report_block.get("assessment")
            or report_block.get("risk_summary")
        )
        try:
            report_md = (
                Path(report_md_path).read_text(encoding="utf-8")
                if report_md_path
                else ""
            )
        except OSError:
            report_md = ""
        body = {
            "status": "completed",
            "statistics": {
                "critical": stats.get("critical", 0),
                "high": stats.get("high", 0),
                "medium": stats.get("medium", 0),
                "low": stats.get("low", 0),
                "info": stats.get("info", 0),
                "total": stats.get("total", 0),
            },
            "findings": findings_out,
            "reportMarkdown": report_md,
        }

    data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Agent-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            print(f"[callback] POST {url} -> {status}", file=sys.stderr)
    except urllib.error.URLError as exc:
        print(f"[callback] POST {url} failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "fixture",
        type=Path,
        nargs="?",
        default=None,
        help="Rust source file to audit (ignored when --inputs-json is given)",
    )
    parser.add_argument(
        "--inputs-json",
        type=Path,
        default=None,
        help=(
            "Path to JSON array of NormalizedInput entries "
            "(matches solguard-server's input-normalizer output). "
            "Triggers AI-first multi-target mode."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("outputs"),
        help="Root directory for report output (default: outputs/)",
    )
    parser.add_argument(
        "--task-id",
        type=str,
        default=None,
        help="Task id (defaults to the fixture stem)",
    )
    parser.add_argument(
        "--degraded",
        action="store_true",
        help="Force degraded mode (skip the AI call even if keys exist)",
    )
    parser.add_argument(
        "--single-file-mode",
        action="store_true",
        help="Force legacy single-file audit even when --inputs-json is supplied.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the bundle dict as JSON on stdout (for CI consumption)",
    )
    parser.add_argument(
        "--emit-events",
        action="store_true",
        help="Emit single-line JSON stage events to stdout for progress tracking",
    )
    parser.add_argument(
        "--callback-url",
        type=str,
        default=None,
        help="POST completion JSON to this URL (mirrors oh -p callback shape)",
    )
    parser.add_argument(
        "--callback-token",
        type=str,
        default=None,
        help="X-Agent-Token for the callback (typically AGENT_CALLBACK_TOKEN)",
    )
    args = parser.parse_args()

    task_id_default = None
    bundle: dict[str, Any] | None = None

    # ---------- multi-target path -----------------------------------------
    if args.inputs_json is not None and not args.single_file_mode:
        try:
            raw_inputs = json.loads(args.inputs_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"failed to read --inputs-json {args.inputs_json}: {exc}"
            print(f"error: {msg}", file=sys.stderr)
            if args.callback_url:
                _post_callback(
                    args.callback_url,
                    args.callback_token,
                    args.task_id or "unknown",
                    None,
                    msg,
                )
            return 2
        if not isinstance(raw_inputs, list):
            print("error: --inputs-json must contain a JSON array", file=sys.stderr)
            return 2
        task_id = args.task_id or "audit"
        task_id_default = task_id
        try:
            bundle = run_audit_multi(
                inputs=raw_inputs,
                output_root=args.output_root,
                task_id=task_id,
                force_degraded=args.degraded,
                emit_events=args.emit_events,
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}"
            print(f"error: run_audit_multi raised: {msg}", file=sys.stderr)
            if args.callback_url:
                _post_callback(args.callback_url, args.callback_token, task_id, None, msg)
            return 3

    # ---------- legacy single-file path -----------------------------------
    else:
        fixture_path: Path | None
        if args.inputs_json is not None and args.single_file_mode:
            try:
                raw_inputs = json.loads(args.inputs_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"error: failed to read --inputs-json: {exc}", file=sys.stderr)
                return 2
            if not isinstance(raw_inputs, list):
                print("error: --inputs-json must contain a JSON array", file=sys.stderr)
                return 2
            fixture_path = _resolve_primary_rust_file(raw_inputs)
            if fixture_path is None:
                print("error: no rust_source input resolved to a readable .rs file", file=sys.stderr)
                return 2
        elif args.fixture is not None:
            fixture_path = args.fixture
        else:
            print("error: either fixture or --inputs-json required", file=sys.stderr)
            return 2

        if not fixture_path.exists():
            msg = f"fixture not found: {fixture_path}"
            print(f"error: {msg}", file=sys.stderr)
            if args.callback_url:
                _post_callback(
                    args.callback_url,
                    args.callback_token,
                    args.task_id or "unknown",
                    None,
                    msg,
                )
            return 2

        task_id = args.task_id or fixture_path.stem
        task_id_default = task_id
        try:
            bundle = run_audit(
                fixture_path=fixture_path,
                output_root=args.output_root,
                task_id=task_id,
                force_degraded=args.degraded,
                emit_events=args.emit_events,
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}"
            print(f"error: run_audit raised: {msg}", file=sys.stderr)
            if args.callback_url:
                _post_callback(args.callback_url, args.callback_token, task_id, None, msg)
            return 3

    if args.callback_url and bundle is not None:
        _post_callback(args.callback_url, args.callback_token, task_id_default or "audit", bundle)

    if args.print_json and bundle is not None:
        print(json.dumps(bundle, ensure_ascii=False, indent=2, default=str))
    elif bundle is not None:
        print(f"[solguard] task={task_id_default} output={bundle.get('output_dir')}")
        print(f"[solguard] decision={bundle['scan_result']['decision']}")
        print(f"[solguard] findings={bundle['scan_result']['statistics']['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
