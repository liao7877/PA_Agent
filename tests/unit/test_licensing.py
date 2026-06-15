"""Unit tests for offline license validation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pa_agent.licensing import crypto
from pa_agent.licensing.storage import (
    StoredLicenseState,
    check_clock_rollback,
    persistent_clock_rollback_detected,
    save_state,
    touch_last_seen,
)
from pa_agent.licensing.validator import LicenseStatus, LicenseValidator


@pytest.fixture()
def keypair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    key = Ed25519PrivateKey.generate()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_path = tmp_path / "public_key.pem"
    pub_path.write_bytes(public_pem)

    def _load_public_key_pem() -> bytes:
        return pub_path.read_bytes()

    monkeypatch.setattr(crypto, "load_public_key_pem", _load_public_key_pem)
    return key


def _issue(
    key: Ed25519PrivateKey,
    *,
    exp: int,
    mid: str | None = "LOCALMID12345678",
    iat: int | None = None,
) -> str:
    payload = {
        "v": 1,
        "lid": "test-license",
        "mid": mid,
        "iat": iat if iat is not None else 1_700_000_000,
        "exp": exp,
        "holder": "tester",
    }
    signature = crypto.sign_payload(key, payload)
    return crypto.encode_license_token(payload, signature)


def test_valid_license(keypair: Ed25519PrivateKey) -> None:
    exp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    token = _issue(keypair, exp=exp, mid=None)
    info = LicenseValidator().validate_token(token)
    assert info.ok
    assert info.status is LicenseStatus.VALID


def test_expired_license(keypair: Ed25519PrivateKey) -> None:
    token = _issue(keypair, exp=1_600_000_000, mid=None)
    info = LicenseValidator().validate_token(token)
    assert info.status is LicenseStatus.EXPIRED


def test_tampered_license_rejected(keypair: Ed25519PrivateKey) -> None:
    exp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    token = _issue(keypair, exp=exp, mid=None)
    payload, signature = crypto.decode_license_token(token)
    payload["exp"] = exp + 86_400
    forged = crypto.encode_license_token(payload, signature)
    info = LicenseValidator().validate_token(forged)
    assert info.status is LicenseStatus.INVALID


def test_check_skips_license_when_running_from_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pa_agent.licensing.validator.is_packaged_build", lambda: False)
    info = LicenseValidator().check()
    assert info.ok
    assert "开发模式" in info.message


def test_check_requires_license_when_packaged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pa_agent.licensing.validator.is_packaged_build", lambda: True)
    info = LicenseValidator().check()
    assert info.status is LicenseStatus.MISSING


def test_iat_in_future_rejected(keypair: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pa_agent.licensing.validator.is_packaged_build", lambda: True)
    future_iat = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp())
    exp = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    token = _issue(keypair, exp=exp, mid=None, iat=future_iat)
    info = LicenseValidator().validate_token(token)
    assert info.status is LicenseStatus.CLOCK_ROLLBACK


def test_registry_clock_rollback_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pa_agent.licensing.storage.license_file_path", lambda: tmp_path / "license_state.json")
    registry: dict[str, int] = {"last_seen_utc": 5000}

    def _read() -> int | None:
        return registry.get("last_seen_utc")

    def _write(ts: int) -> None:
        registry["last_seen_utc"] = ts

    monkeypatch.setattr("pa_agent.licensing.storage._registry_read_last_seen", _read)
    monkeypatch.setattr("pa_agent.licensing.storage._registry_write_last_seen", _write)
    assert persistent_clock_rollback_detected(now_utc=4000)
    assert check_clock_rollback(0, now_utc=4000)


def test_embedded_public_key_integrity() -> None:
    from pa_agent.licensing.embedded_pubkey import get_embedded_public_key_pem

    pem = get_embedded_public_key_pem()
    assert b"BEGIN PUBLIC KEY" in pem


def test_clock_rollback_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pa_agent.licensing.storage.license_file_path", lambda: tmp_path / "license_state.json")
    state = StoredLicenseState(
        license_token="x",
        license_id="id",
        machine_id="mid",
        expires_at=9_999_999_999,
        activated_at=1_000,
        last_seen_utc=5_000,
    )
    save_state(state)
    assert check_clock_rollback(5_000, now_utc=4_000)
    with pytest.raises(ValueError, match="回拨"):
        touch_last_seen(state, now_utc=4_000)
