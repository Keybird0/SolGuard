# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Tiny shared LLM client wrapper used by Gate2 and Gate3.

Why not reuse ``AIAnalyzer`` directly?
--------------------------------------
``AIAnalyzer`` is welded to the dual-role L3 prompt (confirmed /
exploratory / rejected). Gates need a **single-shot JSON** round-trip with
their own schema, usually with a colder temperature. This module
:func:`call_json` wraps the same underlying provider dispatch (Anthropic /
OpenAI) while exposing a minimal, injectable interface:

* :func:`call_json(system, user, *, temperature, model)` → ``dict``
* :func:`set_default_llm` / :func:`reset_default_llm` for test-time stubs

When no API key is available :func:`call_json` raises
:class:`LLMUnavailable`; gate callers catch this and record the candidate's
``gate_traces[...] = {"applied": False, "reason": "no LLM"}`` so the gate
degrades gracefully instead of crashing the pipeline.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Protocol

import httpx
import json_repair
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

__all__ = [
    "LLMUnavailable",
    "call_json",
    "set_default_llm",
    "reset_default_llm",
    "GateLLM",
]


class LLMUnavailable(RuntimeError):
    """Raised when no provider is configured — gates degrade on this."""


class GateLLM(Protocol):
    """Callable protocol a gate expects. Accepts a single ``prompt`` string
    (system + user concatenated) and returns a JSON-ready dict."""

    def __call__(self, prompt: str) -> dict[str, Any]:  # pragma: no cover
        ...


_RETRYABLE = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


_default_override: GateLLM | None = None


def set_default_llm(fn: GateLLM | None) -> None:
    """Install a test-time stub for :func:`call_json`.

    Pass ``None`` to reset. Per-gate overrides take precedence via
    ``set_gate_llm`` on each gate module.
    """
    global _default_override
    _default_override = fn


def reset_default_llm() -> None:
    set_default_llm(None)


def _provider() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def _parse_json_or_repair(text: str) -> dict[str, Any]:
    """Lenient JSON parse mirroring :mod:`ai.analyzer._parse_model_reply`."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    try:
        obj = json_repair.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except Exception:  # noqa: BLE001
        pass
    return {"parse_error": "non-dict reply", "raw": cleaned[:400]}


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)
def _call_provider(
    provider: str,
    system: str,
    user: str,
    *,
    temperature: float,
    model: str | None,
    max_output_tokens: int,
    timeout: int,
) -> str:
    if provider == "anthropic":
        from anthropic import Anthropic

        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        chosen = model or os.environ.get(
            "ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"
        )
        resp = client.messages.create(
            model=chosen,
            max_tokens=max_output_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
            timeout=timeout,
        )
        return "".join(
            b.text for b in getattr(resp, "content", [])
            if getattr(b, "type", "") == "text"
        )
    # openai (OrbitAI / Moonshot / LM-Studio via OPENAI_BASE_URL)
    from openai import OpenAI

    base_url = os.environ.get("OPENAI_BASE_URL")
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=base_url,
    ) if base_url else OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    chosen = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    resp = client.chat.completions.create(
        model=chosen,
        temperature=temperature,
        max_tokens=max_output_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        timeout=timeout,
    )
    return (resp.choices[0].message.content or "").strip()


def call_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.1,
    model: str | None = None,
    max_output_tokens: int = 2048,
    timeout: int = 60,
    override: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a single LLM round-trip and return a JSON dict.

    Order of precedence:

    1. Explicit ``override`` arg (tests inject stubs here).
    2. Gate-level override installed via the gate module's
       ``set_gate_llm`` helper (per-gate, not shown here).
    3. Module-wide :func:`set_default_llm`.
    4. Real provider dispatch if ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``
       is present.

    Raises :class:`LLMUnavailable` when none of the above apply.
    """
    if override is not None:
        return override(system + "\n\n" + user)
    if _default_override is not None:
        return _default_override(system + "\n\n" + user)

    provider = _provider()
    if provider is None:
        raise LLMUnavailable("no LLM provider configured")
    text = _call_provider(
        provider,
        system,
        user,
        temperature=temperature,
        model=model,
        max_output_tokens=max_output_tokens,
        timeout=timeout,
    )
    return _parse_json_or_repair(text)
