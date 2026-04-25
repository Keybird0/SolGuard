# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""solana_parse tool — extract structure from Anchor / Native-Rust source.

This is the **MVP regex-plus-brace-balancer** parser. It intentionally does
NOT depend on a full Rust AST (tree-sitter is reserved for Task P2.2.2).
The goal is to give the downstream scanner (`solana_scan`) enough structure
to run the 7 Phase-2 rules reliably on the 5 fixtures we ship with.

Shape
-----
Return type is :class:`core.types.ParsedContract`. Populated fields:

* ``functions``         — every ``(pub )?fn name(...) -> ReturnType`` with its line / args / return type / block span
* ``accounts``          — every ``#[derive(Accounts)] pub struct Name<'info> { ... }`` with its field list
* ``instructions``      — public functions inside a ``#[program] mod ...`` block
* ``anchor_attrs``      — flat list of ``#[account(...)]`` attribute occurrences (seeds / signer / has_one / mut / owner)
* ``metadata``          — parser version + ``declare_id`` / program module name / line count
* ``parse_error``       — set iff the parser bailed early (empty source, file missing, I/O error)

Design notes
------------
* Rust source can have nested braces (``fn f() { match x { .. } }``), so we
  do NOT use a naive ``re.search(r'\\{.*?\\}')``. :func:`_balanced_block`
  walks the source byte-by-byte counting ``{`` / ``}`` while respecting
  string and comment boundaries well enough for our fixtures.
* Comments: line (``//``) and block (``/* ... */``) are skipped. Nested
  block comments are not supported (Rust allows them, but none of our
  fixtures use them).
* The parser is **total**: bad input returns an empty :class:`ParsedContract`
  with ``parse_error`` set, never raises.

Upgrade path
------------
When `tree-sitter-rust` is added (P2.2.2), replace :func:`parse_source` only.
The :func:`execute` entry point and the :class:`ParsedContract` shape stay
fixed, so downstream consumers don't need to change.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.types import ParsedContract

__all__ = [
    "SolanaParseTool",
    "execute",
    "parse_file",
    "parse_source",
]


_PARSER_VERSION = "regex-v0.2.0"


# ---------------------------------------------------------------------------
# Low-level lexing helpers
# ---------------------------------------------------------------------------


def _strip_comments(src: str) -> str:
    """Replace comments with same-length whitespace to preserve line numbers.

    We keep the byte offsets stable so that ``line = code[:m.start()].count('\\n') + 1``
    still works on the stripped text.
    """
    out = list(src)
    i, n = 0, len(src)
    in_line = False
    in_block = False
    in_str = False
    str_quote = ""
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
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
                i += 2
                continue
            if ch == str_quote:
                in_str = False
            i += 1
            continue
        if ch == '"' or ch == "'":
            in_str = True
            str_quote = ch
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
        i += 1
    return "".join(out)


def _balanced_block(src: str, open_idx: int) -> int:
    """Return the index *after* the ``}`` that closes the block starting at ``open_idx``.

    ``src[open_idx]`` must equal ``{``. Returns ``-1`` on unbalanced input.
    """
    if open_idx >= len(src) or src[open_idx] != "{":
        return -1
    depth = 0
    i = open_idx
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _line_of(src: str, offset: int) -> int:
    return src.count("\n", 0, offset) + 1


# ---------------------------------------------------------------------------
# Regex building blocks
# ---------------------------------------------------------------------------


_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"

_FN_HEADER_RE = re.compile(
    rf"""
    (?P<is_pub>\bpub\s+)?            # optional `pub`
    fn\s+(?P<name>{_IDENT})\s*
    \((?P<args>[^)]*)\)\s*
    (?:->\s*(?P<ret>[^{{;]+?))?      # return type (non-greedy, until `{{` or `;`)
    \s*(?={{)                        # must be followed by body
    """,
    re.VERBOSE,
)

_ACCOUNTS_STRUCT_RE = re.compile(
    rf"""
    \#\[derive\([^)]*\bAccounts\b[^)]*\)\]\s*
    (?:\#\[[^\]]*\]\s*)*             # allow other attribute macros in between
    pub\s+struct\s+(?P<name>{_IDENT})
    \s*(?:<[^>]*>)?\s*               # optional generics like <'info>
    (?=\{{)
    """,
    re.VERBOSE,
)

_PROGRAM_MOD_RE = re.compile(
    rf"\#\[program\]\s*(?:pub\s+)?mod\s+(?P<name>{_IDENT})\s*(?=\{{)",
)

_DECLARE_ID_RE = re.compile(r"declare_id!\s*\(\s*\"(?P<id>[^\"]+)\"\s*\)")


def _find_account_attrs(src: str) -> list[tuple[int, str]]:
    """Locate every ``#[account(...)]`` attribute, respecting nested ``[]`` / ``()``.

    Returns a list of ``(start_offset, body)`` where ``body`` is the text
    inside the outermost ``(...)``.
    """
    results: list[tuple[int, str]] = []
    needle = "#[account("
    i = 0
    n = len(src)
    while True:
        j = src.find(needle, i)
        if j == -1:
            break
        open_paren = j + len(needle) - 1
        depth = 0
        k = open_paren
        close = -1
        while k < n:
            c = src[k]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    close = k
                    break
            k += 1
        if close == -1:
            i = j + len(needle)
            continue
        if close + 1 >= n or src[close + 1] != "]":
            i = close + 1
            continue
        body = src[open_paren + 1 : close]
        results.append((j, body))
        i = close + 2
    return results


# ---------------------------------------------------------------------------
# Field / attribute helpers
# ---------------------------------------------------------------------------


def _classify_account_type(ty: str) -> str:
    """Collapse a field type string into a short category.

    Used by downstream rules to reason about "authority-like" fields without
    re-parsing Rust generics.
    """
    t = ty.strip()
    if t.startswith("Signer"):
        return "Signer"
    if t.startswith("Account<"):
        return "Account"
    if t.startswith("Box<Account<"):
        return "Account"
    if t.startswith("UncheckedAccount"):
        return "UncheckedAccount"
    if t.startswith("AccountInfo"):
        return "AccountInfo"
    if t.startswith("Program<"):
        return "Program"
    if t.startswith("SystemAccount"):
        return "SystemAccount"
    if t.startswith("Sysvar<"):
        return "Sysvar"
    if t.startswith("InterfaceAccount<"):
        return "InterfaceAccount"
    return "Other"


_ATTR_FLAGS = {
    "signer": re.compile(r"\bsigner\b"),
    "mut": re.compile(r"\bmut\b"),
    "init": re.compile(r"\binit\b"),
    "init_if_needed": re.compile(r"\binit_if_needed\b"),
    "bump": re.compile(r"\bbump\b"),
    "close": re.compile(r"\bclose\s*="),
}


def _parse_account_attr(body: str) -> dict[str, Any]:
    """Extract high-value tokens from inside an ``#[account(...)]`` body."""
    info: dict[str, Any] = {"raw": body.strip()}
    for flag, rx in _ATTR_FLAGS.items():
        if rx.search(body):
            info[flag] = True
    seeds_match = re.search(r"seeds\s*=\s*\[(?P<seeds>[^\]]*)\]", body, re.DOTALL)
    if seeds_match:
        info["seeds"] = seeds_match.group("seeds").strip()
    has_one = re.findall(rf"has_one\s*=\s*({_IDENT})", body)
    if has_one:
        info["has_one"] = has_one
    owner = re.search(rf"owner\s*=\s*([A-Za-z_][\w:]*)", body)
    if owner:
        info["owner"] = owner.group(1)
    return info


def _skip_attr(src: str, i: int) -> int:
    """Given ``src[i] == '#'``, skip past the matching ``]`` respecting nesting.

    Returns the index right after ``]``; returns ``i + 1`` if the attribute
    looks malformed so the outer loop can make progress.
    """
    n = len(src)
    if i + 1 >= n or src[i + 1] != "[":
        return i + 1
    depth = 0
    paren = 0
    j = i + 1
    while j < n:
        c = src[j]
        if c == "(":
            paren += 1
        elif c == ")":
            paren -= 1
        elif c == "[" and paren == 0:
            depth += 1
        elif c == "]" and paren == 0:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def _read_type_until_comma(src: str, i: int) -> tuple[str, int]:
    """Read a Rust type starting at ``src[i]``, stopping at the top-level ``,``.

    Tracks nesting for ``<>``, ``()`` and ``[]`` so generics like
    ``Account<'info, Vault>`` survive.
    """
    angle = paren = bracket = 0
    n = len(src)
    start = i
    while i < n:
        c = src[i]
        if c == "<":
            angle += 1
        elif c == ">":
            angle = max(0, angle - 1)
        elif c == "(":
            paren += 1
        elif c == ")":
            paren = max(0, paren - 1)
        elif c == "[":
            bracket += 1
        elif c == "]":
            bracket = max(0, bracket - 1)
        elif c == "," and angle == paren == bracket == 0:
            return src[start:i].strip(), i
        elif c == "}" and angle == paren == bracket == 0:
            return src[start:i].strip(), i
        i += 1
    return src[start:i].strip(), i


def _extract_fields(struct_body: str, struct_base_offset: int, whole_src: str) -> list[dict[str, Any]]:
    """Scan a ``#[derive(Accounts)] struct { ... }`` body field-by-field.

    Implementation note: a pure regex ran into two sharp edges that broke on
    the Phase-2 fixtures — ``#[account(seeds = [b\"vault\"])]`` (nested ``]``)
    and ``Account<'info, Vault>`` (comma inside generics). The scanner below
    tracks both.
    """
    fields: list[dict[str, Any]] = []
    src = struct_body
    n = len(src)
    i = 0
    pending_attrs: list[dict[str, Any]] = []

    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c == "#":
            end = _skip_attr(src, i)
            attr_text = src[i:end]
            for off, body in _find_account_attrs(attr_text):
                del off  # offset relative to attr_text — not needed here
                pending_attrs.append(_parse_account_attr(body))
            i = end
            continue
        # Otherwise expect `pub ident : Type ,`
        m = re.match(rf"pub\s+(?P<name>{_IDENT})\s*:\s*", src[i:])
        if not m:
            i += 1
            continue
        field_start = i
        name = m.group("name")
        i += m.end()
        ty, i = _read_type_until_comma(src, i)
        fields.append(
            {
                "name": name,
                "ty": ty,
                "type_category": _classify_account_type(ty),
                "attrs": pending_attrs,
                "line": _line_of(whole_src, struct_base_offset + field_start),
            }
        )
        pending_attrs = []
        if i < n and src[i] == ",":
            i += 1
    return fields


# ---------------------------------------------------------------------------
# Core extractors
# ---------------------------------------------------------------------------


def _extract_functions(code: str) -> list[dict[str, Any]]:
    fns: list[dict[str, Any]] = []
    for m in _FN_HEADER_RE.finditer(code):
        brace_idx = code.find("{", m.end())
        end = _balanced_block(code, brace_idx) if brace_idx != -1 else -1
        fns.append(
            {
                "name": m.group("name"),
                "is_pub": bool(m.group("is_pub")),
                "args": (m.group("args") or "").strip(),
                "return_type": (m.group("ret") or "").strip(),
                "line": _line_of(code, m.start()),
                "body_start": brace_idx if brace_idx != -1 else None,
                "body_end": end if end != -1 else None,
            }
        )
    return fns


def _extract_accounts(code: str) -> list[dict[str, Any]]:
    structs: list[dict[str, Any]] = []
    for m in _ACCOUNTS_STRUCT_RE.finditer(code):
        brace_idx = code.find("{", m.end())
        end = _balanced_block(code, brace_idx)
        if brace_idx == -1 or end == -1:
            continue
        body = code[brace_idx + 1 : end - 1]
        structs.append(
            {
                "name": m.group("name"),
                "line": _line_of(code, m.start()),
                "fields": _extract_fields(body, brace_idx + 1, code),
            }
        )
    return structs


def _extract_instructions(code: str) -> list[dict[str, Any]]:
    program = _PROGRAM_MOD_RE.search(code)
    if not program:
        return []
    brace_idx = code.find("{", program.end())
    end = _balanced_block(code, brace_idx)
    if brace_idx == -1 or end == -1:
        return []
    body = code[brace_idx + 1 : end - 1]
    body_offset = brace_idx + 1
    instrs: list[dict[str, Any]] = []
    for m in _FN_HEADER_RE.finditer(body):
        if not m.group("is_pub"):
            continue
        instrs.append(
            {
                "name": m.group("name"),
                "args": (m.group("args") or "").strip(),
                "return_type": (m.group("ret") or "").strip(),
                "line": _line_of(code, body_offset + m.start()),
                "program_mod": program.group("name"),
            }
        )
    return instrs


def _extract_anchor_attrs(code: str) -> list[dict[str, Any]]:
    attrs: list[dict[str, Any]] = []
    for offset, body in _find_account_attrs(code):
        info = _parse_account_attr(body)
        info["line"] = _line_of(code, offset)
        attrs.append(info)
    return attrs


def _extract_metadata(code: str, original: str) -> dict[str, Any]:
    md: dict[str, Any] = {
        "parser": _PARSER_VERSION,
        "line_count": original.count("\n") + (0 if original.endswith("\n") else 1),
        "has_anchor_prelude": "anchor_lang::prelude::*" in original,
    }
    declare = _DECLARE_ID_RE.search(code)
    if declare:
        md["declare_id"] = declare.group("id")
    program = _PROGRAM_MOD_RE.search(code)
    if program:
        md["program_mod"] = program.group("name")
    return md


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_source(code: str, file_path: str = "<inline>") -> ParsedContract:
    """Parse a Rust source string into a :class:`ParsedContract`.

    Total function: unexpected input types or parser exceptions are swallowed
    into :attr:`ParsedContract.parse_error` — this keeps the tool usable as a
    last-line defense in the SOP pipeline.
    """
    try:
        if not code or not code.strip():
            return ParsedContract(
                file_path=file_path,
                source_code=code if isinstance(code, str) else "",
                parse_error="empty source",
            )
        stripped = _strip_comments(code)
        functions = _extract_functions(stripped)
        accounts = _extract_accounts(stripped)
        instructions = _extract_instructions(stripped)
        anchor_attrs = _extract_anchor_attrs(stripped)
        metadata = _extract_metadata(stripped, code)
        return ParsedContract(
            file_path=file_path,
            source_code=code,
            functions=functions,
            accounts=accounts,
            instructions=instructions,
            anchor_attrs=anchor_attrs,
            metadata=metadata,
        )
    except Exception as exc:  # pragma: no cover — defensive
        return ParsedContract(
            file_path=file_path,
            source_code=code if isinstance(code, str) else "",
            parse_error=f"parse failed: {type(exc).__name__}: {exc}",
        )


def parse_file(path: Path | str) -> ParsedContract:
    """Parse a file from disk; ``parse_error`` is set on I/O failures."""
    p = Path(path)
    if not p.exists():
        return ParsedContract(
            file_path=str(p),
            parse_error=f"file not found: {p}",
        )
    try:
        code = p.read_text(encoding="utf-8")
    except OSError as exc:
        return ParsedContract(
            file_path=str(p),
            parse_error=f"read failed: {exc}",
        )
    return parse_source(code, str(p))


# ---------------------------------------------------------------------------
# OpenHarness Tool wrapper
# ---------------------------------------------------------------------------


def execute(
    code: str | None = None,
    code_path: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness Tool entry point.

    Exactly one of ``code`` or ``code_path`` must be provided. The return
    dict is ``ParsedContract.to_dict()`` and is safe to round-trip through
    :meth:`core.types.ParsedContract.from_dict`.
    """
    if code is not None and code_path is not None:
        raise ValueError("provide only one of 'code' or 'code_path'")
    if code is None and code_path is None:
        raise ValueError("either 'code' or 'code_path' is required")

    if code_path is not None:
        parsed = parse_file(code_path)
    else:
        assert code is not None
        parsed = parse_source(code)
    return parsed.to_dict()


class SolanaParseTool:
    """Stateless wrapper so the Skill runner can instantiate a Tool object.

    The OpenHarness runtime treats any class with an ``execute`` method as a
    Tool, so keeping a class around — even if it just forwards — lets the
    agent reference ``tools.SolanaParseTool`` without an import alias.
    """

    name: str = "solana_parse"
    version: str = _PARSER_VERSION

    def execute(
        self,
        code: str | None = None,
        code_path: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return execute(code=code, code_path=code_path, **kwargs)
