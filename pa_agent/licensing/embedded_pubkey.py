"""Embedded Ed25519 public key for packaged builds (auto-generated).

Regenerate after rotating keys:
    python tools/sync_embedded_pubkey.py
"""
from __future__ import annotations

import base64
import hashlib

_PUBLIC_KEY_PEM_B64 = "LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS0KTUNvd0JRWURLMlZ3QXlFQUp2U2RWNmRMUG9vUG9lbGwyakdFRFNHeERVYjd5Qnp5clVhRy9CRWtyTVE9Ci0tLS0tRU5EIFBVQkxJQyBLRVktLS0tLQo="
_PUBLIC_KEY_SHA256 = "0c3e8fb71a66753355a5ca939ba17be3416958d89c8fa022f7052032a1790659"


def get_embedded_public_key_pem() -> bytes:
    pem = base64.b64decode(_PUBLIC_KEY_PEM_B64.encode("ascii"))
    digest = hashlib.sha256(pem).hexdigest()
    if digest != _PUBLIC_KEY_SHA256:
        raise RuntimeError("embedded public key integrity check failed")
    return pem
