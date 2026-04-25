# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""solana_scan tool — 7 low-confidence hint emitters for Solana sources.

Contract
--------
This module is deliberately thin: every rule is a **pure function** of
:class:`core.types.ParsedContract` and returns a list of hint dicts. Hints are
*suggestions* (``confidence="low"``), not verdicts — the final ``is_valid``
judgement is delegated to the :mod:`ai.analyzer` cross-validation pass.

Rule id ↔ anchor ↔ reference
----------------------------
Each rule id matches an anchor inside
``references/vulnerability-patterns.md`` so the AI can look up severity /
recommendation text without needing the Python side to hardcode it.

Hint schema
-----------
``{
    "rule_id": str,           # stable id, matches vulnerability-patterns.md anchor
    "location": str,          # "<file-or-fixture>:<line>"
    "code_snippet": str,      # <=200 chars, trimmed
    "confidence": "low",      # always "low" here — upgrade path owned by AI
    "why": str,               # ≥20 chars, plain English
    "references_anchor": str, # "#missing_signer_check" etc.
}``

Design notes
------------
* Each rule runs inside a ``try/except`` barrier; a single rule failure is
  recorded in ``scan_errors`` and never aborts the batch.
* Rules operate only on structures already produced by
  :mod:`tools.solana_parse`. They deliberately do **not** re-parse source
  beyond lightweight regex scanning where the parse layer doesn't expose
  enough context (e.g. bare arithmetic, ``invoke``/``invoke_signed`` call
  sites).
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any, Callable

from core.types import ParsedContract

__all__ = [
    "SolanaScanTool",
    "execute",
    "scan",
]


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Field-name heuristics. Rules split by name-class so the same "AccountInfo"
# field doesn't accidentally trigger both missing_signer_check and
# missing_owner_check at once.
_SIGNER_LIKE_NAMES = {"authority", "admin", "owner", "signer", "payer", "delegate"}
_DATA_LIKE_NAMES = {
    "config",
    "state",
    "data",
    "metadata",
    "treasury",
    "vault_data",
    "pool_state",
    "market_state",
    "escrow",
    "position",
    "cache",
}

_UNVALIDATED_TYPES = {"AccountInfo", "UncheckedAccount"}

_NUMERIC_FIELDS = (
    "balance",
    "amount",
    "supply",
    "value",
    "total",
    "count",
    "fee",
    "fee_bps",
    "reserves",
    "lamports",
    "size",
)

_KNOWN_PROGRAM_IDENTIFIERS = {
    "system_program",
    "token_program",
    "associated_token_program",
    "rent",
    "clock",
    "spl_token",
    "anchor_spl",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int = 200) -> str:
    """Trim and collapse whitespace for safe inclusion in a hint payload."""
    clean = " ".join(text.split())
    if len(clean) > max_len:
        return clean[: max_len - 1] + "…"
    return clean


def _file_stem(parsed: ParsedContract) -> str:
    """Short filename used in ``location``. Falls back to ``<inline>`` for strings."""
    path = parsed.file_path or "<inline>"
    return Path(path).name if path not in ("<inline>", "") else "<inline>"


def _snippet_at(source: str, offset: int, span: int = 80) -> str:
    """Extract a small window around ``offset`` from ``source`` for hint snippets."""
    start = max(0, offset - span // 2)
    end = min(len(source), offset + span)
    return _truncate(source[start:end])


def _line_from_offset(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


@functools.lru_cache(maxsize=64)
def _strip_comments_and_strings(source: str) -> str:
    """Replace line/block comments and string contents with spaces.

    We keep offsets stable so line numbers remain accurate. Only used by
    the regex-based rules that would otherwise match inside ``"..."`` or
    ``// ...`` and produce nuisance hints.

    Phase 6 note: result is ``lru_cache``-memoized because four different
    regex rules call this on the same source per ``scan()`` invocation —
    profiling (`outputs/phase6-profile.md`) showed ~75% of the CPU budget
    inside ``solana_scan`` going to this function before the cache.
    """
    out = list(source)
    i, n = 0, len(source)
    in_line = False
    in_block = False
    in_str = False
    quote = ""
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
            else:
                out[i] = " "
            i += 1
            continue
        if in_block:
            if ch == "*" and nxt == "/":
                out[i] = " "
                out[i + 1] = " "
                i += 2
                in_block = False
            else:
                if ch != "\n":
                    out[i] = " "
                i += 1
            continue
        if in_str:
            if ch == "\\" and nxt:
                out[i] = " "
                out[i + 1] = " "
                i += 2
                continue
            if ch == quote:
                in_str = False
            else:
                out[i] = " "
            i += 1
            continue
        if ch == "/" and nxt == "/":
            out[i] = " "
            out[i + 1] = " "
            i += 2
            in_line = True
            continue
        if ch == "/" and nxt == "*":
            out[i] = " "
            out[i + 1] = " "
            i += 2
            in_block = True
            continue
        if ch in ('"', "'"):
            in_str = True
            quote = ch
            i += 1
            continue
        i += 1
    return "".join(out)


def _function_ranges(parsed: ParsedContract) -> list[tuple[str, int, int]]:
    """Return ``(name, body_start, body_end)`` for every parsed function with a body."""
    ranges: list[tuple[str, int, int]] = []
    for fn in parsed.functions:
        start = fn.get("body_start")
        end = fn.get("body_end")
        if isinstance(start, int) and isinstance(end, int) and end > start:
            ranges.append((fn.get("name", "?"), start, end))
    return ranges


def _make_hint(
    rule_id: str,
    parsed: ParsedContract,
    line: int,
    snippet: str,
    why: str,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "location": f"{_file_stem(parsed)}:{line}",
        "code_snippet": _truncate(snippet),
        "confidence": "low",
        "why": why,
        "references_anchor": f"#{rule_id}",
    }


# ---------------------------------------------------------------------------
# Rule 1 — missing_signer_check
# ---------------------------------------------------------------------------


def check_missing_signer_check(parsed: ParsedContract) -> list[dict[str, Any]]:
    """Unchecked authority-like account that never goes through ``Signer``.

    Heuristic:

    * Field name ∈ :data:`_SIGNER_LIKE_NAMES`.
    * Field type category ∈ :data:`_UNVALIDATED_TYPES` (raw ``AccountInfo`` /
      ``UncheckedAccount``).
    * No ``#[account(signer[=true])]`` attribute on the field.
    """
    hints: list[dict[str, Any]] = []
    for struct in parsed.accounts:
        for field in struct.get("fields", []):
            name = field.get("name", "")
            if name not in _SIGNER_LIKE_NAMES:
                continue
            category = field.get("type_category", "")
            if category not in _UNVALIDATED_TYPES:
                continue
            attrs: list[dict[str, Any]] = field.get("attrs", [])
            if any(attr.get("signer") for attr in attrs):
                continue
            line = field.get("line")
            snippet = f"pub {name}: {field.get('ty', '')}"
            hints.append(
                _make_hint(
                    rule_id="missing_signer_check",
                    parsed=parsed,
                    line=line if isinstance(line, int) else 0,
                    snippet=snippet,
                    why=(
                        f"Field `{name}` is an authority-like account declared as "
                        f"`{field.get('ty', '?')}` with no Signer constraint; "
                        "any caller can forge it."
                    ),
                )
            )
    return hints


# ---------------------------------------------------------------------------
# Rule 2 — missing_owner_check
# ---------------------------------------------------------------------------


def _attr_has_owner_binding(attr: dict[str, Any]) -> bool:
    return bool(attr.get("owner") or attr.get("seeds") or attr.get("has_one"))


def check_missing_owner_check(parsed: ParsedContract) -> list[dict[str, Any]]:
    """Raw ``AccountInfo`` / ``UncheckedAccount`` fields with no ownership binding.

    Focused on data-like names (``config``, ``state``, ``metadata``, etc.) to
    avoid stepping on :func:`check_missing_signer_check`'s toes for
    authority-named fields.
    """
    hints: list[dict[str, Any]] = []
    for struct in parsed.accounts:
        for field in struct.get("fields", []):
            name = field.get("name", "")
            if name in _SIGNER_LIKE_NAMES:
                continue
            if name not in _DATA_LIKE_NAMES and not any(
                tok in name for tok in _DATA_LIKE_NAMES
            ):
                continue
            category = field.get("type_category", "")
            if category not in _UNVALIDATED_TYPES:
                continue
            attrs: list[dict[str, Any]] = field.get("attrs", [])
            if any(_attr_has_owner_binding(a) for a in attrs):
                continue
            line = field.get("line")
            snippet = f"pub {name}: {field.get('ty', '')}"
            hints.append(
                _make_hint(
                    rule_id="missing_owner_check",
                    parsed=parsed,
                    line=line if isinstance(line, int) else 0,
                    snippet=snippet,
                    why=(
                        f"Field `{name}` is a raw {category} with no owner/seeds/has_one "
                        "binding; any account whose bytes happen to deserialize "
                        "could be accepted."
                    ),
                )
            )
    return hints


# ---------------------------------------------------------------------------
# Rule 3 — integer_overflow
# ---------------------------------------------------------------------------


_ARITH_RE = re.compile(
    r"(?P<op>(?<![A-Za-z0-9_])"  # op not preceded by identifier char
    r"(?P<lhs>\b\w+\.("
    + "|".join(_NUMERIC_FIELDS)
    + r"))\s*"
    r"(?P<sym>[+\-*])\s*"
    r"(?P<rhs>[\w\.\(\)]+))",
)


def check_integer_overflow(parsed: ParsedContract) -> list[dict[str, Any]]:
    """Unchecked ``+`` / ``-`` / ``*`` on numeric account fields.

    Only fires inside parsed instruction bodies (parsed functions with a body
    span). Lines that reference ``checked_`` within 40 characters of the
    operator are treated as already guarded.
    """
    source = _strip_comments_and_strings(parsed.source_code)
    if not source:
        return []
    hints: list[dict[str, Any]] = []
    for _name, start, end in _function_ranges(parsed):
        body = source[start:end]
        for m in _ARITH_RE.finditer(body):
            abs_offset = start + m.start()
            window_start = max(0, abs_offset - 40)
            window_end = min(len(source), abs_offset + 40)
            if "checked_" in source[window_start:window_end]:
                continue
            line = _line_from_offset(parsed.source_code, abs_offset)
            snippet = _snippet_at(parsed.source_code, abs_offset)
            hints.append(
                _make_hint(
                    rule_id="integer_overflow",
                    parsed=parsed,
                    line=line,
                    snippet=snippet,
                    why=(
                        f"Raw `{m.group('sym')}` on `{m.group('lhs')}` without "
                        "`checked_*` — Anchor release builds disable overflow checks."
                    ),
                )
            )
    return hints


# ---------------------------------------------------------------------------
# Rule 4 — arbitrary_cpi
# ---------------------------------------------------------------------------


_INVOKE_RE = re.compile(r"\binvoke(_signed)?\s*\(")
_PROGRAM_ID_ASSIGN_RE = re.compile(
    r"program_id\s*:\s*\*?\s*ctx\.accounts\.(?P<acct>\w+)\.key"
)


def check_arbitrary_cpi(parsed: ParsedContract) -> list[dict[str, Any]]:
    """Detect CPI dispatch whose target program comes unchecked from user input.

    Heuristic:

    * The function body contains an ``invoke(...)`` or ``invoke_signed(...)``
      call.
    * The body sets ``program_id: *ctx.accounts.<name>.key`` (or a close
      variant) — i.e. trusts a caller-supplied account as the target program.
    * No ``require_keys_eq!(ctx.accounts.<name>.key(), ...)`` guard appears
      between the assignment and the invoke call.
    """
    source = _strip_comments_and_strings(parsed.source_code)
    if not source:
        return []
    hints: list[dict[str, Any]] = []
    for _name, start, end in _function_ranges(parsed):
        body = source[start:end]
        if not _INVOKE_RE.search(body):
            continue
        for m in _PROGRAM_ID_ASSIGN_RE.finditer(body):
            acct = m.group("acct")
            if acct in _KNOWN_PROGRAM_IDENTIFIERS:
                continue
            guard_re = re.compile(
                rf"require_keys_eq!\s*\(\s*ctx\.accounts\.{re.escape(acct)}\.key\s*\("
            )
            if guard_re.search(body):
                continue
            abs_offset = start + m.start()
            line = _line_from_offset(parsed.source_code, abs_offset)
            hints.append(
                _make_hint(
                    rule_id="arbitrary_cpi",
                    parsed=parsed,
                    line=line,
                    snippet=_snippet_at(parsed.source_code, abs_offset, span=120),
                    why=(
                        f"CPI target program_id is read from `ctx.accounts.{acct}.key` "
                        "without a `require_keys_eq!` whitelist — attacker can "
                        "substitute a malicious program executing under current seeds."
                    ),
                )
            )
    return hints


# ---------------------------------------------------------------------------
# Rule 5 — account_data_matching
# ---------------------------------------------------------------------------


_MANUAL_DESERIALIZE_RE = re.compile(
    r"("
    r"(?P<targ1>\w+)::try_from_slice\s*\(\s*&?(?P<src1>\w+)"
    r"|(?P<targ2>\w+)::deserialize\s*\(\s*&\s*mut\s*&?(?P<src2>[\w.]+)"
    r"|(?P<src3>\w+)\.try_borrow(_mut)?_data\s*\(\s*\)"
    r")",
)


def _raw_account_field_names(parsed: ParsedContract) -> set[str]:
    """Names of every field declared as raw AccountInfo / UncheckedAccount."""
    names: set[str] = set()
    for struct in parsed.accounts:
        for field in struct.get("fields", []):
            if field.get("type_category") in _UNVALIDATED_TYPES:
                name = field.get("name")
                if isinstance(name, str) and name:
                    names.add(name)
    return names


def check_account_data_matching(parsed: ParsedContract) -> list[dict[str, Any]]:
    """Manual deserialization of a *raw* AccountInfo without discriminator check.

    Phase 6 tuning (Round 1, 2026-04-25):
        - Only fire when the variable being deserialized resolves to a raw
          ``AccountInfo`` / ``UncheckedAccount`` field in the parsed account
          structs. Previous implementation fired on *any* deserialize call as
          long as *any* raw field existed in the file, which drove the top
          FP cluster in the baseline (`account_data_matching` 5/23 FPs).
        - Dedup across the whole file on ``(source_var, target_struct)`` so
          repeated `try_from_slice` calls on the same variable (typical in
          read / write instruction pairs) collapse to a single hint.
    """
    source = _strip_comments_and_strings(parsed.source_code)
    if not source:
        return []
    raw_names = _raw_account_field_names(parsed)
    if not raw_names:
        return []
    hints: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for m in _MANUAL_DESERIALIZE_RE.finditer(source):
        # Unify which variable is being dereferenced; target may be empty for
        # try_borrow_data (third branch) — that branch already embeds the var.
        src = m.group("src1") or m.group("src2") or m.group("src3") or ""
        target = m.group("targ1") or m.group("targ2") or "?"
        # Strip ``.data.borrow()`` / ``.data`` tail and any struct accessor so
        # we can correlate against our raw-field name set.
        root = src.split(".", 1)[0]
        if root not in raw_names:
            continue
        key = (root, target)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        line = _line_from_offset(parsed.source_code, m.start())
        hints.append(
            _make_hint(
                rule_id="account_data_matching",
                parsed=parsed,
                line=line,
                snippet=_snippet_at(parsed.source_code, m.start()),
                why=(
                    f"`{root}` is a raw AccountInfo field and is manually "
                    f"deserialized into `{target}` without Anchor's "
                    "discriminator/owner check — attacker-owned bytes can "
                    "spoof the struct."
                ),
            )
        )
    return hints


# ---------------------------------------------------------------------------
# Rule 6 — pda_derivation_error
# ---------------------------------------------------------------------------


_INVOKE_SIGNED_SEEDS_RE = re.compile(
    r"invoke_signed\s*\([^)]*?(?P<seeds>&?\[[^\]]*\])",
    re.DOTALL,
)


def _normalise_seed(fragment: str) -> str:
    """Collapse a seed fragment down to its essential byte-literal tokens."""
    tokens = re.findall(r'b"([^"]*)"', fragment)
    return ",".join(tokens)


def check_pda_derivation_error(parsed: ParsedContract) -> list[dict[str, Any]]:
    """Mismatch between ``#[account(seeds = [...])]`` and the seeds passed to ``invoke_signed``.

    Conservative: only fire when the attribute-side seeds produce at least
    one byte literal that is absent from the invoke-side seeds.
    """
    source = _strip_comments_and_strings(parsed.source_code)
    if not source:
        return []
    attr_seeds: list[str] = []
    for attr in parsed.anchor_attrs:
        seeds = attr.get("seeds")
        if isinstance(seeds, str):
            attr_seeds.append(_normalise_seed(seeds))
    if not attr_seeds:
        return []
    hints: list[dict[str, Any]] = []
    for m in _INVOKE_SIGNED_SEEDS_RE.finditer(source):
        invoke_seed = _normalise_seed(m.group("seeds"))
        if not invoke_seed:
            continue
        if any(s and s.split(",")[0] in invoke_seed for s in attr_seeds):
            continue
        line = _line_from_offset(parsed.source_code, m.start())
        hints.append(
            _make_hint(
                rule_id="pda_derivation_error",
                parsed=parsed,
                line=line,
                snippet=_snippet_at(parsed.source_code, m.start(), span=120),
                why=(
                    "`invoke_signed` seeds do not overlap with any "
                    "`#[account(seeds = ...)]` literal in this module — "
                    "likely derivation drift between account constraint and CPI."
                ),
            )
        )
    return hints


# ---------------------------------------------------------------------------
# Rule 7 — uninitialized_account
# ---------------------------------------------------------------------------


def check_uninitialized_account(parsed: ParsedContract) -> list[dict[str, Any]]:
    """``init_if_needed`` usage missing mandatory companions (``payer`` or ``space``)."""
    hints: list[dict[str, Any]] = []
    for attr in parsed.anchor_attrs:
        if not attr.get("init_if_needed"):
            continue
        raw = attr.get("raw", "")
        missing: list[str] = []
        if "payer" not in raw:
            missing.append("payer")
        if "space" not in raw and "zero" not in raw:
            missing.append("space/zero")
        if not missing:
            continue
        line_val = attr.get("line")
        line = int(line_val) if isinstance(line_val, int) else 0
        hints.append(
            _make_hint(
                rule_id="uninitialized_account",
                parsed=parsed,
                line=line,
                snippet=_truncate(raw),
                why=(
                    f"`init_if_needed` is present but the attribute is missing "
                    f"{', '.join(missing)}; re-initialization may silently clobber "
                    "state from a previous run."
                ),
            )
        )
    return hints


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


_RuleFn = Callable[[ParsedContract], list[dict[str, Any]]]

_RULES: list[_RuleFn] = [
    check_missing_signer_check,
    check_missing_owner_check,
    check_integer_overflow,
    check_arbitrary_cpi,
    check_account_data_matching,
    check_pda_derivation_error,
    check_uninitialized_account,
]


def _count_by_rule(hints: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for h in hints:
        rid = h.get("rule_id", "unknown")
        counts[rid] = counts.get(rid, 0) + 1
    counts["total"] = len(hints)
    return counts


def _dedup_by_location(hints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for h in hints:
        key = (h.get("rule_id", ""), h.get("location", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def scan(parsed: ParsedContract) -> dict[str, Any]:
    """Run every registered rule. Returns a dict with three keys.

    ``hints``         — deduplicated list of low-confidence findings
    ``scan_errors``   — per-rule errors (rule name + exception repr); empty on success
    ``statistics``    — counts keyed by ``rule_id`` + a ``total`` key
    """
    hints: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for fn in _RULES:
        rule_id = fn.__name__.replace("check_", "")
        try:
            hints.extend(fn(parsed))
        except Exception as exc:  # noqa: BLE001
            errors.append({"rule_id": rule_id, "error": f"{type(exc).__name__}: {exc}"})
    hints = _dedup_by_location(hints)
    return {
        "hints": hints,
        "scan_errors": errors,
        "statistics": _count_by_rule(hints),
    }


# ---------------------------------------------------------------------------
# OpenHarness Tool wrapper
# ---------------------------------------------------------------------------


def execute(
    parsed: dict[str, Any] | ParsedContract | None = None,
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness tool entry point.

    Accepts either a pre-parsed :class:`ParsedContract` or its ``to_dict()``
    form so the tool can be chained after ``solana_parse`` without reserializing.
    """
    if parsed is None:
        raise ValueError("'parsed' argument is required")
    if isinstance(parsed, ParsedContract):
        pc = parsed
    else:
        pc = ParsedContract.from_dict(parsed)
    return scan(pc)


class SolanaScanTool:
    """OpenHarness Tool class — thin wrapper so the runtime can discover it."""

    name: str = "solana_scan"
    version: str = "v0.1.0"

    def execute(
        self,
        parsed: dict[str, Any] | ParsedContract | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return execute(parsed=parsed, **kwargs)
