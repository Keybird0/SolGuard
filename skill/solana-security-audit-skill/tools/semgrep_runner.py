# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Thin ``semgrep`` CLI wrapper.

Produces the **raw** semgrep JSON (``{"results": [...], "errors": [...]}``)
and hands it to the AI layer unmodified. The AI-first pipeline expects
``semgrep_raw`` to be evidence, not a verdict.

Derived structurally from ``Contract_Security_Audit_Skill/skill/scripts/
semgrep_runner.py`` (MIT) but rewritten for:

1. **No upstream ``rpc_common`` dependency** — uses ``subprocess`` directly.
2. **No result reshaping** — returns semgrep's own JSON verbatim, so the AI
   still sees severity strings, ``extra.message`` text, and ``check_id``.
3. **Graceful degradation** — any installation/CLI/parse failure returns
   ``{"results": [], "tool_error": "<reason>"}`` rather than raising.

Timeout / exit-code semantics
-----------------------------
* ``semgrep`` exits **1** when it *finds* matches — we treat that as success.
* ``semgrep`` exits **2** on config / CLI errors — we surface the stderr.
* Default timeout is 60 seconds (configurable).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

__all__ = ["DEFAULT_RULES_DIR", "SemgrepRunner", "execute", "run"]


_DEFAULT_TIMEOUT = 60

# ``<skill-root>/assets/semgrep-rules``. Computed at import time so callers
# don't need to pass it explicitly in the common case.
_SKILL_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_RULES_DIR: Path = _SKILL_ROOT / "assets" / "semgrep-rules"


def _tool_error(reason: str) -> dict[str, Any]:
    return {"results": [], "errors": [], "tool_error": reason}


def run(
    target_path: str | Path,
    rules_dir: str | Path | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Execute ``semgrep`` and return the raw JSON plus a ``tool_error`` key.

    Parameters
    ----------
    target_path
        File or directory to scan. Must exist.
    rules_dir
        Directory holding ``*.yaml`` rules. Defaults to
        :data:`DEFAULT_RULES_DIR`. The directory must exist and be non-empty.
    timeout
        Subprocess timeout in seconds.
    """
    if shutil.which("semgrep") is None:
        return _tool_error("semgrep CLI not installed")

    target = Path(target_path)
    if not target.exists():
        return _tool_error(f"target not found: {target}")

    rules = Path(rules_dir) if rules_dir else DEFAULT_RULES_DIR
    if not rules.exists():
        return _tool_error(f"rules directory not found: {rules}")
    if rules.is_dir() and not any(rules.glob("*.yaml")):
        return _tool_error(f"rules directory contains no *.yaml: {rules}")

    cmd = [
        "semgrep",
        "--json",
        "--quiet",
        "--no-git-ignore",
        "--metrics=off",
        "--disable-version-check",
        "--config",
        str(rules),
        str(target),
    ]

    try:
        proc = subprocess.run(  # noqa: S603 — caller controls inputs
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _tool_error(f"semgrep timeout after {timeout}s")
    except FileNotFoundError:
        return _tool_error("semgrep executable vanished mid-run")

    # Exit code semantics:
    #   0 = scan OK, no findings
    #   1 = findings exist
    #   2 = errors (but stdout is still usually valid JSON if at least some
    #       rules parsed). We try to salvage partial output first, and only
    #       fall back to ``tool_error`` if the JSON is genuinely unusable.
    stdout = proc.stdout or ""
    if stdout.strip():
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            payload = None
            parse_err: str | None = f"semgrep JSON parse failed: {exc}"
        else:
            parse_err = None
    else:
        payload = None
        parse_err = None

    if not isinstance(payload, dict):
        if proc.returncode >= 2:
            stderr_tail = (proc.stderr or "").strip().splitlines()[-3:]
            return _tool_error(
                f"semgrep exit={proc.returncode}: {' | '.join(stderr_tail)[:400]}"
            )
        return _tool_error(parse_err or "semgrep returned no JSON output")

    payload.setdefault("results", [])
    payload.setdefault("errors", [])
    # Surface non-fatal exit code as an annotation without dropping results.
    payload["tool_error"] = (
        f"semgrep exit={proc.returncode} with {len(payload.get('errors', []))} rule errors"
        if proc.returncode >= 2
        else None
    )
    return payload


def execute(
    target_path: str | Path | None = None,
    rules_dir: str | Path | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    **_: Any,
) -> dict[str, Any]:
    if target_path is None:
        return _tool_error("target_path argument is required")
    return run(target_path=target_path, rules_dir=rules_dir, timeout=timeout)


class SemgrepRunner:
    """OpenHarness Tool wrapper — delegates to :func:`run`."""

    name: str = "semgrep_runner"
    version: str = "v0.1.0"

    def execute(
        self,
        target_path: str | Path | None = None,
        rules_dir: str | Path | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return execute(
            target_path=target_path,
            rules_dir=rules_dir,
            timeout=timeout,
            **kwargs,
        )
