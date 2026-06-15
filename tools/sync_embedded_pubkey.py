#!/usr/bin/env python3
"""Sync pa_agent/licensing/public_key.pem into embedded_pubkey.py for release builds."""
from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEM_PATH = ROOT / "pa_agent" / "licensing" / "public_key.pem"
OUT_PATH = ROOT / "pa_agent" / "licensing" / "embedded_pubkey.py"

TEMPLATE = '''"""Embedded Ed25519 public key for packaged builds (auto-generated).

Regenerate after rotating keys:
    python tools/sync_embedded_pubkey.py
"""
from __future__ import annotations

import base64
import hashlib

_PUBLIC_KEY_PEM_B64 = "{b64}"
_PUBLIC_KEY_SHA256 = "{sha256}"


def get_embedded_public_key_pem() -> bytes:
    pem = base64.b64decode(_PUBLIC_KEY_PEM_B64.encode("ascii"))
    digest = hashlib.sha256(pem).hexdigest()
    if digest != _PUBLIC_KEY_SHA256:
        raise RuntimeError("embedded public key integrity check failed")
    return pem
'''


def main() -> int:
    if not PEM_PATH.is_file():
        print(f"Missing public key: {PEM_PATH}", file=sys.stderr)
        print("Run: python tools/license_keygen.py generate-keys", file=sys.stderr)
        return 1

    pem = PEM_PATH.read_bytes()
    if b"BEGIN PUBLIC KEY" not in pem:
        print(f"Invalid PEM file: {PEM_PATH}", file=sys.stderr)
        return 1

    b64 = base64.b64encode(pem).decode("ascii")
    sha256 = hashlib.sha256(pem).hexdigest()
    OUT_PATH.write_text(
        TEMPLATE.format(b64=b64, sha256=sha256),
        encoding="utf-8",
    )
    print(f"Synced embedded public key -> {OUT_PATH}")
    print(f"SHA256: {sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
