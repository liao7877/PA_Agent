"""Embedded Ed25519 public key for packaged builds (auto-generated).

Regenerate after rotating keys:
    python tools/sync_embedded_pubkey.py
"""
from __future__ import annotations

import base64
import hashlib

_PUBLIC_KEY_PEM_B64 = "LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS0NCk1Db3dCUVlESzJWd0F5RUFKdlNkVjZkTFBvb1BvZWxsMmpHRURTR3hEVWI3eUJ6eXJVYUcvQkVrck1RPQ0KLS0tLS1FTkQgUFVCTElDIEtFWS0tLS0tDQo="
_PUBLIC_KEY_SHA256 = "4b4def141f4b50e54ff87c0089c46154e23d7a20c94191fbf6c844c08a383a86"


def get_embedded_public_key_pem() -> bytes:
    pem = base64.b64decode(_PUBLIC_KEY_PEM_B64.encode("ascii"))
    digest = hashlib.sha256(pem).hexdigest()
    if digest != _PUBLIC_KEY_SHA256:
        raise RuntimeError("embedded public key integrity check failed")
    return pem
