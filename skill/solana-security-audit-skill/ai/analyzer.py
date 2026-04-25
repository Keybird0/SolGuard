# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""LLM cross-validation + exploratory analysis for SolGuard.

Exposes a single public class :class:`AIAnalyzer` whose
:meth:`cross_validate_and_explore` method bundles:

1. Prompt assembly from the AI-first evidence package (parse + scan hints +
   semgrep raw + source).
2. Provider dispatch — Anthropic by default, OpenAI fallback. Both clients
   are constructed lazily so the module stays import-safe on machines with
   no API key.
3. Retry with :mod:`tenacity` (two attempts, 60 s wall clock each).
4. Three-stage JSON parsing:

   - ``json.loads`` (fast path)
   - :func:`json_repair.loads` (fix trailing commas, unquoted keys, …)
   - Structured degradation: return
     ``{"confirmed": [], "exploratory": [], "rejected": [],
       "parse_error": "<reason>", "raw": "<prefix>"}``

5. Optional token-usage pass-through when the provider supplies it.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Literal

import httpx
import json_repair
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from .prompts import SOLANA_AUDIT_SYSTEM_PROMPT, build_user_prompt
from .prompts_v2 import (
    PROMPT_VERSION_V2,
    SOLANA_AUDIT_SYSTEM_PROMPT_V2,
    build_user_prompt_v2,
)

__all__ = [
    "AIAnalyzer",
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "PROMPT_VERSION_V1",
    "PROMPT_VERSION_V2",
]


DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
DEFAULT_OPENAI_MODEL = "gpt-4o"

# Version token for the default (legacy) prompt. Benchmarks stratify by
# ``token_usage.prompt_version`` so round1-scan / round2-prompt runs can be
# compared apples-to-apples in compare_benchmarks.py.
PROMPT_VERSION_V1 = "v1.2026-04-01"

_RETRYABLE_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


ProviderName = Literal["anthropic", "openai"]


class AIAnalyzer:
    """Single-shot LLM auditor.

    Parameters
    ----------
    provider
        ``"anthropic"`` (default) or ``"openai"``.
    model
        Model id override. When omitted, uses
        :data:`DEFAULT_ANTHROPIC_MODEL` / :data:`DEFAULT_OPENAI_MODEL`.
    timeout
        Per-request wall-clock timeout in seconds. Default 60.
    api_key
        Override for the provider key (otherwise read from
        ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``).
    temperature
        Sampling temperature. Default 0.2 to keep the JSON stable.
    max_output_tokens
        Ceiling for provider response. Default 4096.
    """

    def __init__(
        self,
        provider: ProviderName = "anthropic",
        model: str | None = None,
        timeout: int = 60,
        api_key: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 4096,
        prompt_version: str | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.provider: ProviderName = provider
        # ``prompt_version`` selects the system prompt + user template pair.
        # Explicit arg wins; otherwise the ``SOLGUARD_PROMPT_VERSION`` env
        # var lets deployments flip without code change.
        env_pv = os.environ.get("SOLGUARD_PROMPT_VERSION")
        chosen_pv = (prompt_version or env_pv or PROMPT_VERSION_V1).strip()
        if chosen_pv == PROMPT_VERSION_V2:
            self._system_prompt = SOLANA_AUDIT_SYSTEM_PROMPT_V2
            self._build_user = build_user_prompt_v2
        else:
            # Treat anything else as v1 (legacy baseline).
            chosen_pv = PROMPT_VERSION_V1
            self._system_prompt = SOLANA_AUDIT_SYSTEM_PROMPT
            self._build_user = build_user_prompt
        self.prompt_version: str = chosen_pv

        # LLM response cache. Explicit arg wins; else env
        # ``SOLGUARD_LLM_CACHE_DIR``; else disabled. Cache key encodes
        # provider/model/prompt_version/user_prompt_sha so two different
        # prompt revisions never collide, even on the same source file.
        env_cache = os.environ.get("SOLGUARD_LLM_CACHE_DIR")
        raw_cache_dir = cache_dir if cache_dir is not None else env_cache
        if raw_cache_dir:
            cdir = Path(raw_cache_dir).expanduser().resolve()
            cdir.mkdir(parents=True, exist_ok=True)
            self._cache_dir: Path | None = cdir
        else:
            self._cache_dir = None
        # Allow env-var override so deployments (e.g. OrbitAI gpt-5.4) can
        # switch model without code changes. Explicit `model=` arg wins.
        model_env = (
            os.environ.get("ANTHROPIC_MODEL")
            if provider == "anthropic"
            else os.environ.get("OPENAI_MODEL")
        )
        self.model: str = model or model_env or (
            DEFAULT_ANTHROPIC_MODEL
            if provider == "anthropic"
            else DEFAULT_OPENAI_MODEL
        )
        self.timeout: int = timeout
        self.temperature: float = temperature
        self.max_output_tokens: int = max_output_tokens
        env_var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        self.api_key: str | None = api_key or os.environ.get(env_var)
        self._client: Any | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cross_validate_and_explore(
        self,
        parse_result: dict[str, Any],
        scan_hints: list[dict[str, Any]],
        semgrep_raw: dict[str, Any],
        source_code: str,
        file_path: str = "<unknown>",
    ) -> dict[str, Any]:
        """Run the dual-role audit.

        Returns a dict with at least
        ``{"confirmed": [...], "exploratory": [...], "rejected": [...]}``.
        On any failure, the arrays are empty and either ``parse_error`` (JSON
        parsing failure) or ``error`` (network / provider failure) is set.
        ``token_usage`` is populated when the provider supplies it.
        """
        if not self.api_key:
            return _degraded(
                error=f"no {self.provider} API key found in environment",
                scan_hints=scan_hints,
            )

        user_prompt = self._build_user(
            parse_result=_safe_dumps(parse_result, max_bytes=24_000),
            scan_hints=_safe_dumps(scan_hints, max_bytes=8_000),
            semgrep_raw=_safe_dumps(semgrep_raw, max_bytes=8_000),
            source_code=_truncate_source(source_code, max_bytes=24_000),
            file_path=file_path,
        )

        # Cache lookup (fast path when same prompt was audited before).
        cache_key = self._cache_key(user_prompt)
        cached = self._cache_get(cache_key) if cache_key else None
        if cached is not None:
            cached.setdefault("token_usage", {}).update(
                {"prompt_version": self.prompt_version, "cache_hit": True}
            )
            return cached

        try:
            raw_text, token_usage = self._invoke_with_retry(user_prompt)
        except Exception as exc:  # noqa: BLE001
            return _degraded(
                error=f"{type(exc).__name__}: {exc}",
                scan_hints=scan_hints,
            )

        parsed = _parse_model_reply(raw_text, token_usage=token_usage)
        if isinstance(parsed.get("token_usage"), dict):
            parsed["token_usage"]["prompt_version"] = self.prompt_version
            parsed["token_usage"]["cache_hit"] = False

        # Only cache successful structured responses — never cache
        # parse_error / degraded outcomes so transient failures aren't
        # frozen into subsequent runs.
        if cache_key and not parsed.get("parse_error") and not parsed.get("error"):
            self._cache_put(cache_key, parsed)
        return parsed

    # ------------------------------------------------------------------
    # LLM response cache
    # ------------------------------------------------------------------

    def _cache_key(self, user_prompt: str) -> str | None:
        """Stable sha256 across provider/model/prompt_version/user_prompt.

        Normalizes the prompt first so run-to-run non-determinism in nested
        tool outputs (semgrep's ``"time"`` / ``"paths": {"scanned": [...]}``
        blocks, absolute workspace paths, and scan timing floats) doesn't
        invalidate the cache for otherwise identical fixtures.
        """
        if self._cache_dir is None:
            return None
        normalized = _normalize_prompt_for_cache(user_prompt)
        h = hashlib.sha256()
        h.update(self.provider.encode("utf-8"))
        h.update(b"|")
        h.update(self.model.encode("utf-8"))
        h.update(b"|")
        h.update(self.prompt_version.encode("utf-8"))
        h.update(b"|")
        h.update(self._system_prompt.encode("utf-8"))
        h.update(b"|")
        h.update(normalized.encode("utf-8"))
        return h.hexdigest()

    def _cache_path(self, key: str) -> Path:
        assert self._cache_dir is not None
        return self._cache_dir / f"{key}.json"

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        if self._cache_dir is None:
            return None
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or "response" not in payload:
            return None
        resp = payload["response"]
        if not isinstance(resp, dict):
            return None
        # Deep-ish copy so callers can mutate without poisoning subsequent hits.
        return json.loads(json.dumps(resp))

    def _cache_put(self, key: str, response: dict[str, Any]) -> None:
        if self._cache_dir is None:
            return
        envelope = {
            "stored_at": time.time(),
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "response": response,
        }
        try:
            self._cache_path(key).write_text(
                json.dumps(envelope, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            # Cache is best-effort — never let a disk error kill an audit.
            pass

    # ------------------------------------------------------------------
    # Provider dispatch
    # ------------------------------------------------------------------

    def _invoke_with_retry(self, user_prompt: str) -> tuple[str, dict[str, Any]]:
        @retry(
            stop=stop_after_attempt(2),
            wait=wait_fixed(2),
            retry=retry_if_exception_type(_RETRYABLE_ERRORS),
            reraise=True,
        )
        def _call() -> tuple[str, dict[str, Any]]:
            if self.provider == "anthropic":
                return self._call_anthropic(user_prompt)
            return self._call_openai(user_prompt)

        return _call()

    def _call_anthropic(self, user_prompt: str) -> tuple[str, dict[str, Any]]:
        client = self._get_anthropic_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_output_tokens,
            temperature=self.temperature,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            timeout=self.timeout,
        )
        text = "".join(
            block.text for block in getattr(resp, "content", [])
            if getattr(block, "type", "") == "text"
        )
        usage = getattr(resp, "usage", None)
        token_usage: dict[str, Any] = {
            "input_tokens": getattr(usage, "input_tokens", None) if usage else None,
            "output_tokens": getattr(usage, "output_tokens", None) if usage else None,
            "model": self.model,
            "provider": "anthropic",
        }
        return text, token_usage

    def _call_openai(self, user_prompt: str) -> tuple[str, dict[str, Any]]:
        client = self._get_openai_client()
        resp = client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_output_tokens,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            timeout=self.timeout,
        )
        choice = resp.choices[0]
        text = (choice.message.content or "").strip()
        usage_obj = getattr(resp, "usage", None)
        token_usage: dict[str, Any] = {
            "input_tokens": getattr(usage_obj, "prompt_tokens", None) if usage_obj else None,
            "output_tokens": getattr(usage_obj, "completion_tokens", None) if usage_obj else None,
            "model": self.model,
            "provider": "openai",
        }
        return text, token_usage

    def _get_anthropic_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self.api_key)
        return self._client

    def _get_openai_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            # Respect OPENAI_BASE_URL (OrbitAI / Moonshot / LM-Studio etc.)
            # — the SDK already honors it, but we pass explicitly so a
            # caller-supplied override doesn't get shadowed by a stale env.
            base_url = os.environ.get("OPENAI_BASE_URL")
            if base_url:
                self._client = OpenAI(api_key=self.api_key, base_url=base_url)
            else:
                self._client = OpenAI(api_key=self.api_key)
        return self._client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


import re as _re  # noqa: E402  (local import to avoid shadowing earlier uses)


# Keys whose full JSON value should be elided from the cache key.
# Values can be arbitrarily nested, so we do a balanced-brace walk rather
# than regex.
_CACHE_STRIP_KEYS: tuple[str, ...] = ("time", "paths")
# Regex patterns for leaf (scalar) fields to strip out.
_CACHE_STRIP_LEAF_PATTERNS: tuple[tuple[str, str], ...] = (
    # semgrep "version" string (bumps with minor updates but payload same)
    (r'"version"\s*:\s*"[^"]+"', '"version":"*"'),
    # Stray float timing fields at any depth
    (
        r'"(rules_parse_time|config_time|core_time|parse_time|match_time|run_time)"\s*:\s*[0-9eE\+\-\.]+',
        r'"\1":0',
    ),
)


def _elide_json_value(text: str, key: str) -> str:
    """Replace the JSON value for ``key`` with a stable placeholder.

    Walks the string finding every ``"key"\\s*:\\s*`` position and uses a
    simple brace/bracket matcher to skip over the matching value (object,
    array, string, or scalar). The replacement is ``"key":"<stripped>"``.
    """
    pattern = _re.compile(rf'"{_re.escape(key)}"\s*:\s*')
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        m = pattern.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        out.append(f'"{key}":"<stripped>"')
        j = m.end()
        if j >= n:
            break
        ch = text[j]
        if ch in "{[":
            # Balanced skip across strings + nested containers.
            stack = [ch]
            k = j + 1
            in_str = False
            while k < n and stack:
                c = text[k]
                if in_str:
                    if c == "\\" and k + 1 < n:
                        k += 2
                        continue
                    if c == '"':
                        in_str = False
                    k += 1
                    continue
                if c == '"':
                    in_str = True
                    k += 1
                    continue
                if c in "{[":
                    stack.append(c)
                elif c in "}]":
                    stack.pop()
                k += 1
            i = k
        elif ch == '"':
            # Skip a JSON string value.
            k = j + 1
            while k < n:
                if text[k] == "\\" and k + 1 < n:
                    k += 2
                    continue
                if text[k] == '"':
                    k += 1
                    break
                k += 1
            i = k
        else:
            # Scalar (number / bool / null) — consume until separator.
            k = j
            while k < n and text[k] not in ",}\n":
                k += 1
            i = k
    return "".join(out)


def _normalize_prompt_for_cache(prompt: str) -> str:
    """Strip known non-deterministic sub-objects so repeated runs hit cache.

    Applied to the *cache key only* — the prompt sent to the LLM is never
    mutated.
    """
    out = prompt
    for key in _CACHE_STRIP_KEYS:
        out = _elide_json_value(out, key)
    for pat, repl in _CACHE_STRIP_LEAF_PATTERNS:
        out = _re.sub(pat, repl, out)
    return out


def _safe_dumps(payload: Any, max_bytes: int = 8_000) -> str:
    """Dump to JSON, trimming oversize structures to keep prompt lean."""
    text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    return text[: max_bytes - 40] + "\n/* ... truncated ... */"


def _truncate_source(source: str, max_bytes: int) -> str:
    raw = source.encode("utf-8")
    if len(raw) <= max_bytes:
        return source
    return raw[: max_bytes - 80].decode("utf-8", errors="ignore") + "\n// ... truncated ..."


def _parse_model_reply(
    raw_text: str,
    token_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Three-stage JSON parse: strict → json_repair → structured degrade."""
    cleaned = _strip_code_fence(raw_text)
    parsed: dict[str, Any] | None = None
    parse_error: str | None = None

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        parse_error = f"strict: {exc.msg}"
        try:
            repaired = json_repair.loads(cleaned)
            if isinstance(repaired, dict):
                parsed = repaired
            else:
                parse_error = f"{parse_error}; json_repair returned non-dict"
        except (ValueError, TypeError) as exc2:
            parse_error = f"{parse_error}; json_repair: {exc2}"

    if not isinstance(parsed, dict):
        return _degraded(
            error=None,
            parse_error=parse_error or "model returned non-object",
            raw_prefix=cleaned[:400],
            token_usage=token_usage,
        )

    confirmed = _coerce_list(parsed.get("confirmed"))
    exploratory = _coerce_list(parsed.get("exploratory"))
    rejected = _coerce_list(parsed.get("rejected"))

    result: dict[str, Any] = {
        "confirmed": confirmed,
        "exploratory": exploratory,
        "rejected": rejected,
    }
    if token_usage is not None:
        result["token_usage"] = token_usage
    if parse_error and not (confirmed or exploratory or rejected):
        result["parse_error"] = parse_error
    return result


def _coerce_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
    return out


def _strip_code_fence(text: str) -> str:
    """Strip markdown ```json fences if the model adds them despite the prompt."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _degraded(
    error: str | None = None,
    parse_error: str | None = None,
    raw_prefix: str | None = None,
    scan_hints: list[dict[str, Any]] | None = None,
    token_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Uniform degraded payload — AI layer never raises through analyzer."""
    result: dict[str, Any] = {
        "confirmed": [],
        "exploratory": [],
        "rejected": [],
    }
    if error is not None:
        result["error"] = error
    if parse_error is not None:
        result["parse_error"] = parse_error
    if raw_prefix is not None:
        result["raw"] = raw_prefix
    if scan_hints:
        # Keep the scan hints in the payload so downstream Markdown can still
        # show "unverified scan evidence" when the LLM was unavailable.
        result["unverified_scan_hints"] = scan_hints
    if token_usage is not None:
        result["token_usage"] = token_usage
    return result
