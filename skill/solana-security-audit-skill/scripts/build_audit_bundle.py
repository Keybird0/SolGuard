"""build_audit_bundle.py — collect a local source tree into an audit bundle.

Phase 1 scaffold. Full implementation lands in Phase 2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def collect(source_dir: Path, limit_mb: float = 10.0) -> dict:
    files: list[str] = []
    total_bytes = 0
    cap_bytes = int(limit_mb * 1024 * 1024)
    for rs_file in source_dir.rglob("*.rs"):
        if any(part in {"target", "node_modules"} for part in rs_file.parts):
            continue
        size = rs_file.stat().st_size
        if total_bytes + size > cap_bytes:
            break
        files.append(str(rs_file.relative_to(source_dir)))
        total_bytes += size
    return {
        "root": str(source_dir),
        "files": files,
        "total_bytes": total_bytes,
        "limit_mb": limit_mb,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect .rs files into an audit bundle.")
    parser.add_argument("source", type=Path, help="Source directory")
    parser.add_argument("--limit-mb", type=float, default=10.0)
    args = parser.parse_args()

    bundle = collect(args.source, args.limit_mb)
    print(json.dumps(bundle, indent=2))


if __name__ == "__main__":
    main()
