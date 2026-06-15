"""Ed25519 license signing helpers."""
from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

LICENSE_PREFIX = "PAAG"
LICENSE_VERSION = 1
_GROUP_SEP = ":"  # must not appear in base64url payload


def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_public_key_pem() -> bytes:
    from pathlib import Path

    from pa_agent.licensing.embedded_pubkey import get_embedded_public_key_pem
    from pa_agent.licensing.packaged import is_packaged_build

    if is_packaged_build():
        return get_embedded_public_key_pem()

    pem_path = Path(__file__).resolve().parent / "public_key.pem"
    if pem_path.is_file():
        return pem_path.read_bytes()
    return get_embedded_public_key_pem()


def load_public_key() -> Ed25519PublicKey:
    return serialization.load_pem_public_key(load_public_key_pem())


def load_private_key_pem(path: str) -> Ed25519PrivateKey:
    data = open(path, "rb").read()
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("private key must be Ed25519")
    return key


def sign_payload(private_key: Ed25519PrivateKey, payload: dict[str, Any]) -> bytes:
    return private_key.sign(canonical_payload_bytes(payload))


def verify_payload(public_key: Ed25519PublicKey, payload: dict[str, Any], signature: bytes) -> bool:
    try:
        public_key.verify(signature, canonical_payload_bytes(payload))
    except InvalidSignature:
        return False
    return True


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def encode_license_token(payload: dict[str, Any], signature: bytes) -> str:
    body = f"{_b64url_encode(canonical_payload_bytes(payload))}.{_b64url_encode(signature)}"
    grouped = _GROUP_SEP.join(body[i : i + 5] for i in range(0, len(body), 5))
    return f"{LICENSE_PREFIX}-{grouped}"


def decode_license_token(token: str) -> tuple[dict[str, Any], bytes]:
    raw = token.strip()
    prefix = f"{LICENSE_PREFIX}-"
    if raw.upper().startswith(prefix):
        raw = raw[len(prefix) :]
    compact = raw.replace(_GROUP_SEP, "")
    if "." not in compact:
        raise ValueError("激活码格式无效")
    payload_part, sig_part = compact.split(".", 1)
    payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    signature = _b64url_decode(sig_part)
    return payload, signature
