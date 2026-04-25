# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Core data structures for SolGuard skill.

These dataclasses are intentionally lightweight (stdlib-only) so they can
be serialized to JSON without pulling pydantic into every caller.

Schema mirror
-------------
The shape here is the canonical Python side of the contract declared in
``skill/solana-security-audit-skill/SKILL.md §Output Contract`` and
``references/report-templates.md``. Downstream consumers:

* ``tools/solana_parse.py`` returns :class:`ParsedContract`.
* ``tools/solana_scan.py`` rules return ``list[Finding]``.
* ``tools/solana_report.py`` consumes :class:`ScanResult`.
* Backend polling endpoint returns ``ScanTask.to_dict()``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, cast


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFO = "Info"

    @classmethod
    def from_value(cls, value: str) -> Severity:
        for member in cls:
            if member.value.lower() == value.lower():
                return member
        raise ValueError(f"Unknown severity: {value!r}")


class TaskStatus(str, Enum):
    PENDING = "pending"
    SCANNING = "scanning"
    ANALYZING = "analyzing"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"

    @classmethod
    def from_value(cls, value: str) -> TaskStatus:
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"Unknown task status: {value!r}")


SourceVisibility = Literal["source", "bytecode_only"]
Decision = Literal["proceed", "degraded", "blocked"]
CallbackStatus = Literal["pending", "sent", "failed", "skipped"]


# ---------------------------------------------------------------------------
# Finding / Statistics
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single security finding raised by a rule or the AI analyzer."""

    id: str
    severity: Severity
    title: str
    location: str
    description: str
    impact: str
    recommendation: str
    rule_id: str | None = None
    code_snippet: str | None = None
    confidence: float | None = None
    kill_signal: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        payload = dict(data)
        payload["severity"] = Severity.from_value(payload["severity"])
        return cls(**payload)


@dataclass
class Statistics:
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0

    @property
    def total(self) -> int:
        return self.critical + self.high + self.medium + self.low + self.info

    def to_dict(self) -> dict[str, int]:
        return {
            "critical": self.critical,
            "high": self.high,
            "medium": self.medium,
            "low": self.low,
            "info": self.info,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> Statistics:
        return cls(
            critical=int(data.get("critical", 0)),
            high=int(data.get("high", 0)),
            medium=int(data.get("medium", 0)),
            low=int(data.get("low", 0)),
            info=int(data.get("info", 0)),
        )

    @classmethod
    def from_findings(cls, findings: list[Finding]) -> Statistics:
        counts: dict[Severity, int] = {s: 0 for s in Severity}
        for f in findings:
            counts[f.severity] += 1
        return cls(
            critical=counts[Severity.CRITICAL],
            high=counts[Severity.HIGH],
            medium=counts[Severity.MEDIUM],
            low=counts[Severity.LOW],
            info=counts[Severity.INFO],
        )


# ---------------------------------------------------------------------------
# Token / Authority (Solana-specific)
# ---------------------------------------------------------------------------


@dataclass
class TokenExtension:
    """One Token-2022 extension observed on a mint.

    Names follow the upstream SPL nomenclature (e.g. ``PermanentDelegate``,
    ``TransferHook``, ``TransferFee``, ``ConfidentialTransfer``,
    ``NonTransferable``). ``red_flag`` is set when the extension gives an
    authority coercive power over downstream holders (see
    ``references/vulnerability-patterns.md``).
    """

    name: str
    params: dict[str, Any] = field(default_factory=dict)
    red_flag: bool = False
    severity_hint: Severity | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "params": dict(self.params),
            "red_flag": self.red_flag,
            "severity_hint": self.severity_hint.value if self.severity_hint else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenExtension:
        hint = data.get("severity_hint")
        return cls(
            name=data["name"],
            params=dict(data.get("params", {})),
            red_flag=bool(data.get("red_flag", False)),
            severity_hint=Severity.from_value(hint) if hint else None,
        )


@dataclass
class AuthorityInfo:
    """Snapshot of the four Solana authority slots that affect security.

    Matches ``SKILL.md §Solana knowledge — Authority risk matrix``. Any
    non-null authority is an attack surface; ``extensions`` surfaces the
    Token-2022 red-flag list.
    """

    mint_authority: str | None = None
    freeze_authority: str | None = None
    update_authority: str | None = None
    program_upgrade_authority: str | None = None
    extensions: list[TokenExtension] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mint_authority": self.mint_authority,
            "freeze_authority": self.freeze_authority,
            "update_authority": self.update_authority,
            "program_upgrade_authority": self.program_upgrade_authority,
            "extensions": [e.to_dict() for e in self.extensions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthorityInfo:
        raw_exts = data.get("extensions", [])
        exts = [TokenExtension.from_dict(e) for e in raw_exts]
        return cls(
            mint_authority=data.get("mint_authority"),
            freeze_authority=data.get("freeze_authority"),
            update_authority=data.get("update_authority"),
            program_upgrade_authority=data.get("program_upgrade_authority"),
            extensions=exts,
        )


# ---------------------------------------------------------------------------
# Reports & Callback (Step 7 output artefacts)
# ---------------------------------------------------------------------------


@dataclass
class ReportBundle:
    """Paths + integrity metadata for the three-tier Markdown reports.

    Produced by ``tools/solana_report.py`` (Step 7). Values in ``sha256``
    and ``bytes`` are keyed by the same short names as the path fields
    (``risk_summary``, ``assessment``, ``checklist``, ``report_json``) so
    CI can verify integrity without re-reading every file.
    """

    risk_summary: str = ""
    assessment: str = ""
    checklist: str = ""
    report_json: str = ""
    sha256: dict[str, str] = field(default_factory=dict)
    bytes: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_summary": self.risk_summary,
            "assessment": self.assessment,
            "checklist": self.checklist,
            "report_json": self.report_json,
            "sha256": dict(self.sha256),
            "bytes": dict(self.bytes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReportBundle:
        return cls(
            risk_summary=data.get("risk_summary", ""),
            assessment=data.get("assessment", ""),
            checklist=data.get("checklist", ""),
            report_json=data.get("report_json", ""),
            sha256=dict(data.get("sha256", {})),
            bytes=dict(data.get("bytes", {})),
        )


@dataclass
class Callback:
    """State of the optional webhook callback (Step 7.3)."""

    url: str | None = None
    status: CallbackStatus = "pending"
    attempts: int = 0
    last_http_status: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "attempts": self.attempts,
            "last_http_status": self.last_http_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Callback:
        raw_status = data.get("status", "pending")
        if raw_status not in ("pending", "sent", "failed", "skipped"):
            raise ValueError(f"Unknown callback status: {raw_status!r}")
        return cls(
            url=data.get("url"),
            status=cast(CallbackStatus, raw_status),
            attempts=int(data.get("attempts", 0)),
            last_http_status=data.get("last_http_status"),
        )


# ---------------------------------------------------------------------------
# Parsed / ScanResult / ScanTask
# ---------------------------------------------------------------------------


@dataclass
class ParsedContract:
    """Structured view of a parsed Solana/Anchor source file."""

    file_path: str
    source_code: str = ""
    functions: list[dict[str, Any]] = field(default_factory=list)
    accounts: list[dict[str, Any]] = field(default_factory=list)
    instructions: list[dict[str, Any]] = field(default_factory=list)
    anchor_attrs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    parse_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParsedContract:
        return cls(
            file_path=data["file_path"],
            source_code=data.get("source_code", ""),
            functions=[dict(x) for x in data.get("functions", [])],
            accounts=[dict(x) for x in data.get("accounts", [])],
            instructions=[dict(x) for x in data.get("instructions", [])],
            anchor_attrs=[dict(x) for x in data.get("anchor_attrs", [])],
            metadata=dict(data.get("metadata", {})),
            parse_error=data.get("parse_error"),
        )


@dataclass
class ScanResult:
    """Aggregate result for one audited target.

    Adds the Solana-specific fields declared in ``SKILL.md §Output Contract``:
    ``authority``, ``inputs_summary``, ``source_visibility``, ``decision``,
    ``reports``, ``callback``. All new fields are optional so existing
    callers stay source-compatible.
    """

    contract_name: str
    contract_path: str
    risk_level: str
    findings: list[Finding]
    statistics: Statistics
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    authority: AuthorityInfo | None = None
    inputs_summary: str = ""
    source_visibility: SourceVisibility = "source"
    decision: Decision = "proceed"
    reports: ReportBundle | None = None
    callback: Callback | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_name": self.contract_name,
            "contract_path": self.contract_path,
            "risk_level": self.risk_level,
            "findings": [f.to_dict() for f in self.findings],
            "statistics": self.statistics.to_dict(),
            "timestamp": self.timestamp,
            "authority": self.authority.to_dict() if self.authority else None,
            "inputs_summary": self.inputs_summary,
            "source_visibility": self.source_visibility,
            "decision": self.decision,
            "reports": self.reports.to_dict() if self.reports else None,
            "callback": self.callback.to_dict() if self.callback else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanResult:
        raw_vis = data.get("source_visibility", "source")
        if raw_vis not in ("source", "bytecode_only"):
            raise ValueError(f"Unknown source_visibility: {raw_vis!r}")
        raw_decision = data.get("decision", "proceed")
        if raw_decision not in ("proceed", "degraded", "blocked"):
            raise ValueError(f"Unknown decision: {raw_decision!r}")
        raw_auth = data.get("authority")
        raw_reports = data.get("reports")
        raw_callback = data.get("callback")
        return cls(
            contract_name=data["contract_name"],
            contract_path=data["contract_path"],
            risk_level=data["risk_level"],
            findings=[Finding.from_dict(f) for f in data.get("findings", [])],
            statistics=Statistics.from_dict(data.get("statistics", {})),
            timestamp=data.get(
                "timestamp", datetime.now(timezone.utc).isoformat()
            ),
            authority=AuthorityInfo.from_dict(raw_auth) if raw_auth else None,
            inputs_summary=data.get("inputs_summary", ""),
            source_visibility=cast(SourceVisibility, raw_vis),
            decision=cast(Decision, raw_decision),
            reports=ReportBundle.from_dict(raw_reports) if raw_reports else None,
            callback=Callback.from_dict(raw_callback) if raw_callback else None,
        )


@dataclass
class ScanTask:
    """End-to-end audit task state."""

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: str | None = None
    result: ScanResult | None = None
    error: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "progress": self.progress,
            "result": self.result.to_dict() if self.result else None,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanTask:
        raw_result = data.get("result")
        return cls(
            task_id=data["task_id"],
            status=TaskStatus.from_value(data.get("status", "pending")),
            progress=data.get("progress"),
            result=ScanResult.from_dict(raw_result) if raw_result else None,
            error=data.get("error"),
            created_at=data.get(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
            completed_at=data.get("completed_at"),
        )
