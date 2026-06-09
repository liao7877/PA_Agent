"""Unit tests for offline license validation."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pa_agent.licensing import crypto
from pa_agent.licensing.storage import StoredLicenseState, check_clock_rollback, save_state, touch_last_seen
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


def _issue(key: Ed25519PrivateKey, *, exp: int, mid: str | None = "LOCALMID12345678") -> str:
    payload = {
        "v": 1,
        "lid": "test-license",
        "mid": mid,
        "iat": 1_700_000_000,
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


def test_check_skips_license_when_running_from_source() -> None:
    assert not getattr(sys, "frozen", False)
    info = LicenseValidator().check()
    assert info.ok
    assert "开发模式" in info.message


def test_check_requires_license_when_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    info = LicenseValidator().check()
    assert info.status is LicenseStatus.MISSING


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
