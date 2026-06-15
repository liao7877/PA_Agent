"""Vendor license issuance helpers shared by CLI and GUI tools."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pa_agent.licensing import crypto
from pa_agent.licensing.machine_id import get_machine_fingerprint
from pa_agent.licensing.validator import LicenseInfo, LicenseValidator

DEFAULT_PRIVATE_KEY = (
    Path(__file__).resolve().parents[2] / "tools" / ".license_keys" / "license_private.pem"
)
DEFAULT_PUBLIC_KEY = Path(__file__).resolve().parent / "public_key.pem"


@dataclass(slots=True)
class IssuedLicense:
    token: str
    license_id: str
    holder: str
    expires_at: int
    expires_at_utc: str
    machine_id: str | None
    machine_label: str


def resolve_machine_id(machine: str | None) -> str | None:
    if not machine or machine.lower() == "any":
        return None
    if machine.lower() == "local":
        return get_machine_fingerprint()
    cleaned = machine.replace("-", "").replace(":", "").strip().upper()
    return cleaned[:16] if cleaned else None


def generate_keypair(
    *,
    private_path: Path,
    public_path: Path | None = None,
) -> tuple[Path, Path]:
    public_path = public_path or DEFAULT_PUBLIC_KEY
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)

    key = Ed25519PrivateKey.generate()
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def issue_license(
    *,
    private_key_path: Path,
    days: int = 30,
    expires: datetime | None = None,
    machine: str = "any",
    license_id: str | None = None,
    holder: str = "",
) -> IssuedLicense:
    if not private_key_path.is_file():
        raise FileNotFoundError(f"找不到私钥文件：{private_key_path}")

    private_key = crypto.load_private_key_pem(str(private_key_path))
    now = datetime.now(timezone.utc)
    if expires is not None:
        exp_dt = expires.astimezone(timezone.utc) if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
    else:
        exp_dt = now + timedelta(days=max(1, days))

    mid = resolve_machine_id(machine)
    lid = license_id or str(uuid.uuid4())
    payload = {
        "v": crypto.LICENSE_VERSION,
        "lid": lid,
        "mid": mid,
        "iat": int(now.timestamp()),
        "exp": int(exp_dt.timestamp()),
        "holder": holder or "",
    }
    signature = crypto.sign_payload(private_key, payload)
    token = crypto.encode_license_token(payload, signature)
    machine_label = "不绑定（任意设备）" if mid is None else mid
    return IssuedLicense(
        token=token,
        license_id=lid,
        holder=holder or "",
        expires_at=int(payload["exp"]),
        expires_at_utc=exp_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        machine_id=mid,
        machine_label=machine_label,
    )


def verify_license_token(token: str) -> LicenseInfo:
    return LicenseValidator().validate_token(token)
