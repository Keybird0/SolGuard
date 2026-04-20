"""solana_parse tool — extract structure from Anchor/Rust source.

Phase 1 scaffold: regex-based placeholder. Full implementation in Phase 2
(see docs/04-SolGuard项目管理/03-Phase2-Skill与工具开发.md §Task P2.2.1).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.types import ParsedContract

_FN_RE = re.compile(r"pub\s+fn\s+(?P<name>\w+)\s*\(", re.MULTILINE)
_ACCOUNTS_RE = re.compile(
    r"#\[derive\(Accounts\)\]\s*pub\s+struct\s+(?P<name>\w+)", re.MULTILINE
)
_PROGRAM_RE = re.compile(r"#\[program\]\s*(?:pub\s+)?mod\s+(?P<name>\w+)", re.MULTILINE)


def parse_source(code: str, file_path: str = "<inline>") -> ParsedContract:
    """Regex-only placeholder parser. Replace with tree-sitter in Phase 6."""
    if not code.strip():
        return ParsedContract(
            file_path=file_path,
            source_code=code,
            parse_error="empty source",
        )

    functions = [{"name": m.group("name"), "line": code[: m.start()].count("\n") + 1} for m in _FN_RE.finditer(code)]
    accounts = [
        {"name": m.group("name"), "line": code[: m.start()].count("\n") + 1}
        for m in _ACCOUNTS_RE.finditer(code)
    ]
    instructions = [
        {"name": m.group("name"), "line": code[: m.start()].count("\n") + 1}
        for m in _PROGRAM_RE.finditer(code)
    ]

    return ParsedContract(
        file_path=file_path,
        source_code=code,
        functions=functions,
        accounts=accounts,
        instructions=instructions,
        anchor_attrs=[],
        metadata={"parser": "regex-v0.1.0"},
    )


def parse_file(path: Path | str) -> ParsedContract:
    path = Path(path)
    if not path.exists():
        return ParsedContract(
            file_path=str(path),
            parse_error=f"file not found: {path}",
        )
    return parse_source(path.read_text(encoding="utf-8"), str(path))


def execute(
    code: str | None = None,
    code_path: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """OpenHarness Tool entry point.

    Exactly one of ``code`` or ``code_path`` must be provided.
    """
    if code and code_path:
        raise ValueError("provide only one of 'code' or 'code_path'")
    if code is None and code_path is None:
        raise ValueError("either 'code' or 'code_path' is required")

    if code_path:
        parsed = parse_file(code_path)
    else:
        assert code is not None
        parsed = parse_source(code)

    return parsed.to_dict()
