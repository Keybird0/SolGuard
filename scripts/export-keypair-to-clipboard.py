#!/usr/bin/env python3
"""Export a Solana keypair JSON to base58 secret key, copied to macOS clipboard.

Use ONLY for importing a Devnet test wallet into Phantom / Solflare / Backpack.
The base58 secret is what Phantom's "Import Private Key" expects.

Security:
  - Never prints the secret to stdout / terminal.
  - Writes to macOS clipboard (pbcopy) only.
  - Reminds the user to clear clipboard after paste.
  - Do NOT run this on a mainnet keypair — Devnet test wallets ONLY.

Usage:
  python3 scripts/export-keypair-to-clipboard.py \
      ~/.config/solana/solguard-test-user.json

Dependencies: none (pure stdlib; bundled base58 encoder).
Tested on: Python 3.10+, macOS (pbcopy).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


# --- Minimal base58 (Bitcoin alphabet, same as Solana) ---
_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    encoded = bytearray()
    while n > 0:
        n, r = divmod(n, 58)
        encoded.append(_ALPHABET[r])
    # preserve leading zero bytes as '1'
    for b in data:
        if b == 0:
            encoded.append(_ALPHABET[0])
        else:
            break
    return encoded[::-1].decode()


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def main() -> None:
    if len(sys.argv) != 2:
        die(f"usage: {sys.argv[0]} <path-to-keypair.json>", code=2)

    path = Path(sys.argv[1]).expanduser()
    if not path.is_file():
        die(f"keypair file not found: {path}")

    # Refuse to touch the default CLI wallet (~/.config/solana/id.json) to avoid
    # accidentally exporting a mainnet wallet.
    if path.resolve() == Path("~/.config/solana/id.json").expanduser().resolve():
        die("refusing to export the default id.json — Devnet test wallets only")

    try:
        arr = json.loads(path.read_text())
    except Exception as exc:
        die(f"not valid JSON: {exc}")

    if not (isinstance(arr, list) and len(arr) == 64 and all(isinstance(x, int) and 0 <= x <= 255 for x in arr)):
        die("expected a 64-byte array (Solana keypair JSON)")

    secret_bytes = bytes(arr)
    b58 = b58encode(secret_bytes)

    # Derive pubkey via `solana-keygen pubkey` — gives a nice confirmation and
    # guards against corrupted keypairs without shelling out to external libs.
    pubkey: str | None = None
    if shutil.which("solana-keygen"):
        try:
            pubkey = subprocess.check_output(
                ["solana-keygen", "pubkey", str(path)],
                text=True,
                timeout=5,
            ).strip()
        except Exception:
            pubkey = None

    if not shutil.which("pbcopy"):
        die("pbcopy not found — are you on macOS? (Linux: pipe to xclip instead)")

    proc = subprocess.run(["pbcopy"], input=b58, text=True)
    if proc.returncode != 0:
        die("pbcopy failed")

    # Shred local variable hint (Python won't truly zero memory, but doesn't hurt)
    del secret_bytes
    del b58

    print("=" * 56)
    print("  base58 secret key copied to macOS clipboard")
    if pubkey:
        print(f"  pubkey confirm: {pubkey}")
    print("=" * 56)
    print()
    print("Next steps:")
    print("  1. Open Phantom → Add / Connect wallet → Import Private Key")
    print("  2. Paste (Cmd+V). Name it 'SolGuard-DevnetTest' or similar.")
    print("  3. IMMEDIATELY clear clipboard:")
    print("     printf '' | pbcopy")
    print()
    print("Phantom → settings → Developer Settings → Testnet mode → enable → pick Devnet.")


if __name__ == "__main__":
    main()
