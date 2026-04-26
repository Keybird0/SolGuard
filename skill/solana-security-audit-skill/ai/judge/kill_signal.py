# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Gate1 — deterministic Kill Signal verification.

For every candidate finding, look up the matching KB pattern (by ``rule_id``
or alias) and evaluate its ``kill_signals`` array against the target source.

Matching rules (kept intentionally simple for hackathon stability):

* ``kind == "regex"`` (default) — evaluate ``re.search(pattern, haystack,
  MULTILINE)`` where ``haystack`` is scoped by ``scope``:

  * ``struct`` — the ``#[derive(Accounts)]`` struct body covering the
    finding's location. **If no owning struct is found the signal is
    skipped** (recorded under ``signals_skipped_no_scope``) — we no
    longer fall back to whole-file regex, which used to over-KILL.
  * ``function_body`` — the ``pub fn`` body that owns the finding line.
    **Same skip-on-unresolved behaviour** as ``struct``.
  * ``struct_or_function`` — union of the two above; skipped only when
    BOTH resolvers come up empty.
  * ``file`` or unknown scope — the full source text (KB author opt-in).

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


def _find_owner_struct(source: str, line: int) -> str | None:
    """Return the #[derive(Accounts)] struct body whose braces enclose ``line``.

    Returns ``None`` when no owning struct is found — the caller (``apply``)
    interprets None as "scope unresolvable, skip this signal" rather than
    silently falling back to the whole file (the old behaviour caused
    over-firing of regex-based KILLs and was tracked as a Phase 6 known
    issue, see docs/04-SolGuard项目管理/13 §架构演进).
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
    return best_body  # may be None — see docstring


def _find_owner_function(source: str, line: int) -> tuple[str | None, str | None]:
    """Return ``(body, function_name)`` for the ``(pub )? fn ...`` owning ``line``.

    Returns ``(None, None)`` when no owning function is found — caller
    interprets that as "scope unresolvable, skip this signal" (see
    :func:`_find_owner_struct` docstring for context).
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
    return best_body, best_name  # both may be None — see docstring


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
) -> tuple[str | None, str | None]:
    """Return ``(haystack, function_name_if_any)`` for a given scope.

    For ``struct`` / ``function_body`` / ``struct_or_function`` scopes a
    return value of ``(None, None)`` means "line could not be resolved
    to that scope" — :func:`apply` then **skips** the signal match rather
    than falling back to the whole file. This conservatively under-KILLs
    (the surviving candidate continues into Gate2/Gate3 LLM judgment),
    fixing the Phase 6 false-KILL caused by global-source over-match.

    Explicit ``file`` scope (KB author opt-in) and unknown scopes fall
    back to the full source as before.
    """
    if line is None:
        return source, None
    scope_norm = (scope or "file").lower()
    if scope_norm == "struct":
        body = _find_owner_struct(source, line)
        return body, None
    if scope_norm == "function_body":
        body, fn_name = _find_owner_function(source, line)
        return body, fn_name
    if scope_norm == "struct_or_function":
        struct = _find_owner_struct(source, line)
        fn, fn_name = _find_owner_function(source, line)
        # Both unresolvable → unresolvable. Otherwise concat what we have;
        # any signal firing in either wins.
        if struct is None and fn is None:
            return None, None
        joined = "\n".join(part for part in (struct, fn) if part is not None)
        return joined, fn_name
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
        skipped_no_scope: list[dict[str, str]] = []
        for sig in signals:
            sig_id = str(sig.get("id") or sig.get("semantics") or "unnamed")
            pattern_re = sig.get("pattern")
            if not pattern_re:
                continue
            checked.append(sig_id)
            scope = str(sig.get("scope", "file"))
            haystack, fn_name = _scope_haystack(source_code, scope, line)
            if haystack is None:
                # Scope unresolvable (struct/function not found around line).
                # Conservatively SKIP this signal rather than fall back to
                # whole-file regex (which used to over-KILL). The candidate
                # stays live and proceeds into Gate2/Gate3 LLM judgment.
                skipped_no_scope.append({"id": sig_id, "scope": scope})
                continue
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
        trace_base: dict[str, Any] = {
            "applied": True,
            "signals_fired": fired,
            "signals_checked": checked,
        }
        if skipped_no_scope:
            trace_base["signals_skipped_no_scope"] = skipped_no_scope
        if fired:
            killed += 1
            rid = cand.rule_id or "<no_rule>"
            killed_rules[rid] = killed_rules.get(rid, 0) + 1
            reason = "; ".join(s["semantics"] or s["id"] for s in fired)
            cand.kill(gate="gate1", reason=f"kill_signal fired: {reason}")
            trace_base["verdict"] = "kill"
            cand.gate_traces["gate1_kill"] = trace_base
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
            trace_base["verdict"] = "pass"
            cand.gate_traces["gate1_kill"] = trace_base
            details.append(
                {
                    "rule_id": cand.rule_id,
                    "location": cand.location,
                    "verdict": "pass",
                    "signals_checked": checked,
                    **(
                        {"signals_skipped_no_scope": [s["id"] for s in skipped_no_scope]}
                        if skipped_no_scope
                        else {}
                    ),
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
