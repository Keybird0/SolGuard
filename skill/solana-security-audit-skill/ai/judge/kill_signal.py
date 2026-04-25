# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Gate1 — deterministic Kill Signal verification.

For every candidate finding, look up the matching KB pattern (by ``rule_id``
or alias) and evaluate its ``kill_signals`` array against the target source.

Matching rules (kept intentionally simple for hackathon stability):

* ``kind == "regex"`` (default) — evaluate ``re.search(pattern, haystack,
  MULTILINE)`` where ``haystack`` is scoped by ``scope``:

  * ``struct`` — the ``#[derive(Accounts)]`` struct body covering the
    finding's location (falls back to ``file`` if none found)
  * ``function_body`` — the ``pub fn`` body that owns the finding line
    (falls back to ``file`` if no function ownership found)
  * ``file`` or anything else — the full source text

* Aggregation: **any** signal firing ⇒ the candidate is marked safely
  excluded (KILL). This matches SolGuard ``prompts_v2`` suppression
  semantics ("any of these idioms → is_valid=false"), which we found is
  the right ratio for Solana where a single canonical guard (e.g.,
  ``Signer<'info>``) is a definitive answer.

Output: mutates ``candidate.gate_traces["gate1_kill"]`` with
``{"applied": bool, "signals_fired": [ids], "signals_checked": [ids],
"verdict": "pass" | "kill"}``. On KILL, ``candidate.kill(gate="gate1",
reason=...)`` is called.

Zero LLM calls.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ai.agents.types import Candidate

__all__ = ["apply", "Gate1Result"]


class Gate1Result(dict):
    """Type alias for the summary dict returned by :func:`apply`."""


_LOCATION_RE = re.compile(r":(?P<line>\d+)\s*$")


def _line_from_location(location: str) -> int | None:
    m = _LOCATION_RE.search(location or "")
    if not m:
        return None
    try:
        return int(m.group("line"))
    except ValueError:
        return None


def _find_owner_struct(source: str, line: int) -> str:
    """Return the #[derive(Accounts)] struct body whose braces enclose ``line``.

    Falls back to the whole source when no owning struct is found. The match
    is cheap regex-plus-brace-balancer (works for our fixtures; upgrade to
    tree-sitter when P2.2.2 lands).
    """
    needle_idx = 0
    best_body: str | None = None
    while True:
        m = re.search(
            r"#\[derive\([^)]*\bAccounts\b[^)]*\)\]",
            source[needle_idx:],
            flags=re.MULTILINE,
        )
        if not m:
            break
        abs_start = needle_idx + m.start()
        brace = source.find("{", abs_start)
        if brace == -1:
            break
        end = _balanced(source, brace)
        if end == -1:
            break
        # Does the struct cover our target line?
        start_line = source.count("\n", 0, abs_start) + 1
        end_line = source.count("\n", 0, end) + 1
        if start_line <= line <= end_line:
            best_body = source[brace:end]
            break
        needle_idx = end
    return best_body if best_body is not None else source


def _find_owner_function(source: str, line: int) -> tuple[str, str | None]:
    """Return ``(body, function_name)`` for the ``(pub )? fn ...`` owning ``line``.

    ``body`` is the function block including the outer braces; falls back to
    the full source when no ownership can be determined. ``function_name``
    is the identifier after ``fn`` or ``None``.
    """
    pattern = re.compile(
        r"(?P<pub>pub\s+)?fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*"
        r"(?:->\s*[^{;]+?)?\s*(?=\{)"
    )
    best_body: str | None = None
    best_name: str | None = None
    for m in pattern.finditer(source):
        brace = source.find("{", m.end())
        if brace == -1:
            continue
        end = _balanced(source, brace)
        if end == -1:
            continue
        start_line = source.count("\n", 0, m.start()) + 1
        end_line = source.count("\n", 0, end) + 1
        if start_line <= line <= end_line:
            best_body = source[brace:end]
            best_name = m.group("name")
    if best_body is None:
        return source, None
    return best_body, best_name


def _balanced(src: str, open_idx: int) -> int:
    """Return index past ``}`` closing the block opened at ``src[open_idx] == '{'``.

    Mirrors ``tools.solana_parse._balanced_block`` but inlined so this module
    stays import-cycle-free.
    """
    if open_idx >= len(src) or src[open_idx] != "{":
        return -1
    depth = 0
    i = open_idx
    n = len(src)
    in_str = False
    str_quote = ""
    while i < n:
        ch = src[i]
        if in_str:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == str_quote:
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            str_quote = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _scope_haystack(
    source: str,
    scope: str,
    line: int | None,
) -> tuple[str, str | None]:
    """Return ``(haystack, function_name_if_any)`` for a given scope.

    Unknown scopes fall back to the whole file so missing metadata never
    silently disables a Kill Signal.
    """
    if line is None:
        return source, None
    scope_norm = (scope or "file").lower()
    if scope_norm == "struct":
        return _find_owner_struct(source, line), None
    if scope_norm == "function_body":
        body, fn_name = _find_owner_function(source, line)
        return body, fn_name
    if scope_norm == "struct_or_function":
        struct = _find_owner_struct(source, line)
        fn, fn_name = _find_owner_function(source, line)
        # Join the two slices; any signal firing in either wins.
        return struct + "\n" + fn, fn_name
    return source, None


def _load_pattern_index(
    kb_patterns: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index KB patterns by every rule_id and alias, pointing at the pattern."""
    index: dict[str, dict[str, Any]] = {}
    for p in kb_patterns:
        if not isinstance(p, dict):
            continue
        ids: list[str] = []
        pid = p.get("id")
        if pid:
            ids.append(str(pid))
        for rid in p.get("rule_ids", []) or []:
            ids.append(str(rid))
        for alias in p.get("aliases", []) or []:
            ids.append(str(alias))
        for ident in ids:
            index.setdefault(ident, p)
    return index


def _pattern_for_candidate(
    candidate: Candidate,
    index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not candidate.rule_id:
        return None
    # Exact rule_id first; then strip semgrep: prefix; then the kb pattern id.
    if candidate.rule_id in index:
        return index[candidate.rule_id]
    bare = candidate.rule_id.split(":", 1)[-1] if ":" in candidate.rule_id else None
    if bare and bare in index:
        return index[bare]
    return None


def apply(
    candidates: list[Candidate],
    *,
    kb_patterns: list[dict[str, Any]],
    source_code: str,
) -> Gate1Result:
    """Apply Gate1 kill-signal checks to every candidate, mutating in place.

    Returns a summary dict::

        {
          "applied": int,            # non-skipped candidates
          "killed": int,
          "killed_rule_distribution": {"missing_signer_check": 2, ...},
          "details": [ { rule_id, verdict, signals_fired, signals_checked, ... } ]
        }
    """
    index = _load_pattern_index(kb_patterns)
    details: list[dict[str, Any]] = []
    killed = 0
    applied = 0
    killed_rules: dict[str, int] = {}
    for cand in candidates:
        if cand.status != "live":
            continue
        pattern = _pattern_for_candidate(cand, index)
        if pattern is None:
            cand.gate_traces["gate1_kill"] = {
                "applied": False,
                "reason": "no KB pattern for rule_id",
            }
            continue
        signals = pattern.get("kill_signals") or []
        if not signals:
            cand.gate_traces["gate1_kill"] = {
                "applied": False,
                "reason": "KB pattern has no kill_signals",
            }
            continue
        applied += 1
        line = _line_from_location(cand.location)
        fired: list[dict[str, Any]] = []
        checked: list[str] = []
        for sig in signals:
            sig_id = str(sig.get("id") or sig.get("semantics") or "unnamed")
            pattern_re = sig.get("pattern")
            if not pattern_re:
                continue
            checked.append(sig_id)
            scope = str(sig.get("scope", "file"))
            haystack, fn_name = _scope_haystack(source_code, scope, line)
            try:
                rx = re.compile(str(pattern_re), flags=re.MULTILINE)
            except re.error as exc:  # noqa: BLE001
                cand.gate_traces.setdefault("gate1_regex_errors", []).append(
                    {"signal_id": sig_id, "error": str(exc)}
                )
                continue
            if fn_name and cand.function_name is None:
                cand.function_name = fn_name
            if rx.search(haystack):
                fired.append(
                    {
                        "id": sig_id,
                        "scope": scope,
                        "semantics": str(sig.get("semantics", "")),
                    }
                )
        if fired:
            killed += 1
            rid = cand.rule_id or "<no_rule>"
            killed_rules[rid] = killed_rules.get(rid, 0) + 1
            reason = "; ".join(s["semantics"] or s["id"] for s in fired)
            cand.kill(gate="gate1", reason=f"kill_signal fired: {reason}")
            cand.gate_traces["gate1_kill"] = {
                "applied": True,
                "verdict": "kill",
                "signals_fired": fired,
                "signals_checked": checked,
            }
            details.append(
                {
                    "rule_id": cand.rule_id,
                    "location": cand.location,
                    "verdict": "kill",
                    "signals_fired": [s["id"] for s in fired],
                    "signals_checked": checked,
                }
            )
        else:
            cand.gate_traces["gate1_kill"] = {
                "applied": True,
                "verdict": "pass",
                "signals_fired": [],
                "signals_checked": checked,
            }
            details.append(
                {
                    "rule_id": cand.rule_id,
                    "location": cand.location,
                    "verdict": "pass",
                    "signals_checked": checked,
                }
            )
    return Gate1Result(
        {
            "gate": "gate1_kill_signal",
            "applied": applied,
            "killed": killed,
            "killed_rule_distribution": killed_rules,
            "details": details,
        }
    )
