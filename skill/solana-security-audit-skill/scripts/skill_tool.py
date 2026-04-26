#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""CLI dispatcher for Claude Code-driven SKILL invocation.

OpenHarness invokes each Tool class's ``.execute(**kwargs)`` method
directly across the Python boundary. Claude Code can only shell out via
Bash, so this dispatcher exposes every tool through one stable
stdin/stdout JSON-RPC contract — without modifying any Tool class
itself.

Usage::

    echo '<json>' | uv run python scripts/skill_tool.py <tool_name>
    uv run python scripts/skill_tool.py <tool_name> < in.json > out.json

The stdin payload is a JSON object whose keys are the keyword arguments
of the named tool's ``execute()`` method. Stdout is the dict returned
by that call, JSON-serialized (with ``default=str`` so dataclasses /
``Path`` objects pass through cleanly). On argument or runtime errors a
non-zero exit code is returned and a JSON error envelope is written to
stdout for the Agent to read.

This file is the **only** place where Claude-Code-style CLI lives;
``solguard-server`` and OpenHarness paths are unaffected.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

_THIS = Path(__file__).resolve()
_SKILL_ROOT = _THIS.parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from tools.semgrep_runner import SemgrepRunner  # noqa: E402
from tools.solana_attack_classify import SolanaAttackClassifyTool  # noqa: E402
from tools.solana_cq_verdict import SolanaCqVerdictTool  # noqa: E402
from tools.solana_judge_lite import SolanaJudgeLiteTool  # noqa: E402
from tools.solana_kill_signal import SolanaKillSignalTool  # noqa: E402
from tools.solana_parse import SolanaParseTool  # noqa: E402
from tools.solana_report import SolanaReportTool  # noqa: E402
from tools.solana_scan import SolanaScanTool  # noqa: E402
from tools.solana_seven_q import SolanaSevenQTool  # noqa: E402

# Map dispatcher tool name → Tool class. Keep keys short and stable;
# they appear in SKILL.md "Claude Code Invocation Pattern".
TOOLS: dict[str, type] = {
    "parse":           SolanaParseTool,
    "scan":            SolanaScanTool,
    "semgrep":         SemgrepRunner,
    "kill_signal":     SolanaKillSignalTool,
    "cq_verdict":      SolanaCqVerdictTool,
    "attack_classify": SolanaAttackClassifyTool,
    "seven_q":         SolanaSevenQTool,
    "judge_lite":      SolanaJudgeLiteTool,
    "report":          SolanaReportTool,
}


def _read_payload(args: argparse.Namespace) -> dict[str, Any]:
    """Read JSON payload from --input file or stdin. Empty payload OK."""
    if args.input:
        text = Path(args.input).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        return {}
    text = text.strip()
    if not text:
        return {}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(
            f"payload must be a JSON object, got {type(payload).__name__}"
        )
    return payload


def _write_result(result: Any, args: argparse.Namespace) -> None:
    text = json.dumps(result, default=str, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="skill_tool",
        description="Claude Code dispatcher for SolGuard SKILL thin tools.",
    )
    parser.add_argument(
        "tool",
        nargs="?",
        choices=sorted(TOOLS.keys()),
        help="Which thin tool to invoke (omit when using --list).",
    )
    parser.add_argument(
        "--input", "-i",
        help="Read JSON payload from this file instead of stdin.",
    )
    parser.add_argument(
        "--output", "-o",
        help="Write JSON result to this file instead of stdout.",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Print the registered tool names and exit.",
    )
    args = parser.parse_args(argv)

    if args.list:
        sys.stdout.write("\n".join(sorted(TOOLS.keys())) + "\n")
        return 0

    if args.tool is None:
        parser.error("missing tool name (use --list to see options)")

    try:
        payload = _read_payload(args)
    except (json.JSONDecodeError, ValueError) as exc:
        _write_result(
            {"error": "invalid_payload", "message": str(exc)}, args,
        )
        return 2

    tool_cls = TOOLS[args.tool]
    try:
        result = tool_cls().execute(**payload)
    except TypeError as exc:
        _write_result(
            {
                "error": "bad_kwargs",
                "tool": args.tool,
                "message": str(exc),
                "expected": "see Tool.execute() signature in tools/",
            },
            args,
        )
        return 2
    except Exception as exc:  # pragma: no cover — defensive
        _write_result(
            {
                "error": "tool_runtime_error",
                "tool": args.tool,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
            args,
        )
        return 1

    _write_result(result, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
