#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""In-process SolGuard audit orchestrator.

Wires the five Phase 2 tools (``solana_parse`` → ``solana_scan`` →
``semgrep_runner`` → ``ai.analyzer`` → ``solana_report``) into a single
command you can run without the OpenHarness agent loop. This is what
``scripts/e2e_smoke.sh`` + ``scripts/e2e_smoke_degraded.sh`` drive.

Behaviour
---------
* With a real ``ANTHROPIC_API_KEY`` or ``OPENAI_API_KEY``, the AI layer
  runs and produces the three Markdown sections. Severity/decision reflect
  the model's verdict.
* Without keys (or on any analyzer error), the orchestrator falls back to
  a deterministic, tool-only "degraded" summary: ``decision="degraded"``,
  Markdown files prefixed with ``DEGRADED — LLM unavailable``, findings
  derived purely from scan hints so the report pipeline still has data.

Usage
-----
```
python scripts/run_audit.py <path-to-rust-file> \
    --output-root outputs/phase2-baseline \
    --task-id 01_missing_signer
```
"""

from __future__ import annotations

import argparse
import json
import os
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
from core.types import Finding, ScanResult, Severity, Statistics  # noqa: E402
from tools.solana_parse import parse_file  # noqa: E402
from tools.solana_report import persist  # noqa: E402
from tools.semgrep_runner import run as semgrep_run  # noqa: E402
from tools.solana_scan import scan  # noqa: E402


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


def _severity_of(rule_id: str) -> Severity:
    table: dict[str, Severity] = {
        "arbitrary_cpi": Severity.CRITICAL,
        "missing_signer_check": Severity.HIGH,
        "missing_owner_check": Severity.HIGH,
        "account_data_matching": Severity.HIGH,
        "pda_derivation_error": Severity.HIGH,
        "integer_overflow": Severity.MEDIUM,
        "uninitialized_account": Severity.MEDIUM,
    }
    return table.get(rule_id, Severity.LOW)


def _findings_from_ai(payload: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for idx, item in enumerate(payload.get("confirmed", []) + payload.get("exploratory", [])):
        try:
            severity = Severity.from_value(str(item.get("severity", "Medium")))
        except ValueError:
            severity = Severity.MEDIUM
        out.append(
            Finding(
                id=f"AI-{idx:03d}",
                rule_id=item.get("rule_id"),
                severity=severity,
                title=item.get("rule_id", "finding").replace("_", " ").title(),
                location=item.get("location", ""),
                description=item.get("reason", ""),
                impact=item.get("reason", ""),
                recommendation=item.get("recommendation", ""),
                code_snippet=item.get("code_snippet"),
                confidence=0.9,
            )
        )
    return out


def _findings_from_scan(scan_hints: list[dict[str, Any]]) -> list[Finding]:
    out: list[Finding] = []
    for idx, h in enumerate(scan_hints):
        rule_id = str(h.get("rule_id", "unknown"))
        severity = _severity_of(rule_id)
        out.append(
            Finding(
                id=f"SCAN-{idx:03d}",
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


def run_audit(
    fixture_path: Path,
    output_root: Path,
    task_id: str,
    force_degraded: bool = False,
    emit_events: bool = False,
) -> dict[str, Any]:
    if emit_events:
        _emit_stage("parse", file=str(fixture_path))
    pc = parse_file(fixture_path)
    if emit_events:
        _emit_stage("scan")
    scan_result = scan(pc)
    if emit_events:
        _emit_stage("semgrep")
    semgrep = semgrep_run(target_path=fixture_path)

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
            parse_result=pc.to_dict(),
            scan_hints=scan_result["hints"],
            semgrep_raw=semgrep,
            source_code=pc.source_code,
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
        findings = _findings_from_ai(ai_payload)
        # Fall back to scan hints if the model returned nothing.
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
    return bundle


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


def _resolve_primary_rust_file(inputs: list[dict[str, Any]]) -> Path | None:
    """Pick the first rust_source entry's primary_file / first *.rs file.

    solguard-server's input-normalizer produces entries shaped
    ``{"kind": "rust_source", "rootDir": "...", "primaryFile": "..."}``.
    ``bytecode_only`` and ``lead_only`` entries are skipped; if none of
    the entries produce a usable Rust file, return ``None`` so the
    caller can emit a degraded report without crashing.
    """
    for entry in inputs:
        kind = entry.get("kind")
        if kind != "rust_source":
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
        # Anchor layout
        for candidate in root_path.rglob("programs/*/src/lib.rs"):
            if "target" in candidate.parts:
                continue
            return candidate
        # Fallback: any .rs file, skip target/ and tests/
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
    """POST the final result back to solguard-server/:taskId/complete.

    Best-effort: a failed callback is logged to stderr but does not fail
    the audit. The HTTP body mirrors what the OpenHarness agent would
    send so ``/complete`` accepts either path interchangeably.
    """
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
        # ``persist()`` returns a dict shaped
        # ``{"report": ReportBundle.to_dict(), ...}`` where the inner bundle
        # exposes ``assessment`` / ``risk_summary`` / ``checklist`` as the
        # on-disk paths to the rendered Markdown files. Prefer the long-form
        # assessment and fall back to risk_summary.
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
            # ``reportUrl`` is omitted when unset — the server schema treats
            # it as ``z.string().url().optional()`` and rejects literal null.
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
            "Overrides the positional fixture argument."
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

    fixture_path: Path | None
    if args.inputs_json is not None:
        try:
            raw_inputs = json.loads(args.inputs_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"failed to read --inputs-json {args.inputs_json}: {exc}"
            print(f"error: {msg}", file=sys.stderr)
            if args.callback_url:
                _post_callback(args.callback_url, args.callback_token, args.task_id or "unknown", None, msg)
            return 2
        if not isinstance(raw_inputs, list):
            print("error: --inputs-json must contain a JSON array", file=sys.stderr)
            return 2
        fixture_path = _resolve_primary_rust_file(raw_inputs)
        if fixture_path is None:
            msg = (
                "no rust_source input resolved to a readable .rs file "
                "(all inputs may be bytecode_only or lead_only)"
            )
            if args.callback_url:
                _post_callback(args.callback_url, args.callback_token, args.task_id or "unknown", None, msg)
            print(f"error: {msg}", file=sys.stderr)
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
            _post_callback(args.callback_url, args.callback_token, args.task_id or "unknown", None, msg)
        return 2

    task_id = args.task_id or fixture_path.stem

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

    if args.callback_url:
        _post_callback(args.callback_url, args.callback_token, task_id, bundle)

    if args.print_json:
        print(json.dumps(bundle, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"[solguard] task={task_id} output={bundle['output_dir']}")
        print(f"[solguard] decision={bundle['scan_result']['decision']}")
        print(f"[solguard] findings={bundle['scan_result']['statistics']['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
