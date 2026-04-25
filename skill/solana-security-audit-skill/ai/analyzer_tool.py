# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""OpenHarness Tool wrapper around :class:`AIAnalyzer`.

This module gives the Agent a single, uniform entry point named
``solana_ai_analyze`` with an ``execute(...)`` method that follows the
same shape as ``SolanaParseTool`` / ``SolanaScanTool`` / ``SemgrepRunner``
/ ``SolanaReportTool``.

The wrapper is intentionally thin: it forwards all inputs to
:meth:`AIAnalyzer.cross_validate_and_explore` and returns its dict
verbatim. Provider / model / API-key selection is deferred to
``AIAnalyzer.__init__`` which reads ``ANTHROPIC_API_KEY`` /
``OPENAI_API_KEY`` from the environment.

Degradation contract
--------------------
When no API key is available or the provider call fails, the underlying
analyzer returns ``{"confirmed": [], "exploratory": [], "rejected": [],
"error": "...", "decision": "degraded"}``. The wrapper surfaces the
same dict — callers (``solana_report`` / ``run_audit.py``) check
``decision == "degraded"`` to emit a DEGRADED banner.
"""

from __future__ import annotations

from typing import Any

from .analyzer import AIAnalyzer, DEFAULT_ANTHROPIC_MODEL, DEFAULT_OPENAI_MODEL

__all__ = ["AIAnalyzerTool", "execute"]


def execute(
    parse_result: dict[str, Any] | None = None,
    scan_hints: list[dict[str, Any]] | None = None,
    semgrep_raw: dict[str, Any] | None = None,
    source_code: str = "",
    file_path: str = "<unknown>",
    provider: str | None = None,
    model: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness Tool entry point for ``solana_ai_analyze``.

    Parameters
    ----------
    parse_result
        Output of ``solana_parse`` (``ParsedContract.to_dict()``).
    scan_hints
        List of hint dicts from ``solana_scan`` (``confidence=low``).
    semgrep_raw
        Raw ``semgrep --json`` output from ``solana_semgrep``.
    source_code
        Truncated source (≤ 24 kB) for attacker-perspective exploration.
    file_path
        File label shown in the AI prompt for anchor context.
    provider / model
        Override ``AIAnalyzer`` defaults; otherwise falls back to
        ``anthropic`` / ``DEFAULT_ANTHROPIC_MODEL`` which match the
        skill's default deployment.
    """
    analyzer = AIAnalyzer(
        provider=provider if provider in {"anthropic", "openai"} else "anthropic",
        model=model,
    )
    return analyzer.cross_validate_and_explore(
        parse_result=parse_result or {},
        scan_hints=scan_hints or [],
        semgrep_raw=semgrep_raw or {},
        source_code=source_code,
        file_path=file_path,
    )


class AIAnalyzerTool:
    """Stateless Tool wrapper matching the OpenHarness runtime contract."""

    name: str = "solana_ai_analyze"
    version: str = "0.1.0"
    default_model: str = DEFAULT_ANTHROPIC_MODEL
    openai_fallback_model: str = DEFAULT_OPENAI_MODEL

    def execute(
        self,
        parse_result: dict[str, Any] | None = None,
        scan_hints: list[dict[str, Any]] | None = None,
        semgrep_raw: dict[str, Any] | None = None,
        source_code: str = "",
        file_path: str = "<unknown>",
        provider: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return execute(
            parse_result=parse_result,
            scan_hints=scan_hints,
            semgrep_raw=semgrep_raw,
            source_code=source_code,
            file_path=file_path,
            provider=provider,
            model=model,
            **kwargs,
        )
