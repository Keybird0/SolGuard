"""Core data structures for SolGuard skill.

These dataclasses are intentionally lightweight (stdlib-only) so they can
be serialized to JSON without pulling pydantic into every caller.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


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
    def from_findings(cls, findings: list[Finding]) -> Statistics:
        counts = {s: 0 for s in Severity}
        for f in findings:
            counts[f.severity] += 1
        return cls(
            critical=counts[Severity.CRITICAL],
            high=counts[Severity.HIGH],
            medium=counts[Severity.MEDIUM],
            low=counts[Severity.LOW],
            info=counts[Severity.INFO],
        )


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
        return cls(**data)


@dataclass
class ScanResult:
    """Aggregate result for one audited target."""

    contract_name: str
    contract_path: str
    risk_level: str
    findings: list[Finding]
    statistics: Statistics
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_name": self.contract_name,
            "contract_path": self.contract_path,
            "risk_level": self.risk_level,
            "findings": [f.to_dict() for f in self.findings],
            "statistics": self.statistics.to_dict(),
            "timestamp": self.timestamp,
        }


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
