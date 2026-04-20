"""AI analyzer — LLM-backed deep analysis + Kill-Signal verification.

Phase 1 scaffold: only the interface is defined. Phase 2 implements the
real Anthropic/OpenAI calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.types import Finding


@dataclass
class AIProviderConfig:
    provider: str = "anthropic"
    model: str = "claude-3-5-sonnet-20241022"
    api_key: str | None = None
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout_s: int = 60


class AIAnalyzer:
    """Wraps calls to Anthropic / OpenAI for audit-oriented prompts.

    Phase 1 stub — all methods return empty / NotImplemented structures so
    downstream tooling can already be wired.
    """

    def __init__(self, config: AIProviderConfig):
        self.config = config

    def deep_analyze(
        self,
        code: str,
        rule_findings: list[Finding],
    ) -> list[Finding]:
        """Return LLM-discovered findings that augment the rule findings.

        Phase 1: returns an empty list to keep the pipeline flowing.
        """
        _ = (code, rule_findings)
        return []

    def verify_finding(
        self,
        code: str,
        finding: Finding,
    ) -> dict[str, Any]:
        """Kill-Signal verification. Phase 1 stub assumes all findings valid."""
        _ = (code, finding)
        return {
            "is_valid": True,
            "confidence": 0.75,
            "reason": "Phase 1 stub — Kill Signal not yet implemented.",
        }

    def generate_fix(
        self,
        code: str,
        finding: Finding,
    ) -> str:
        """Produce a suggested patch. Phase 1 stub returns the recommendation."""
        _ = code
        return finding.recommendation
