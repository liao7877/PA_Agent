"""Encrypted license persistence and monotonic clock anchor."""
from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_CLOCK_TOLERANCE_SECONDS = 300
_REGISTRY_KEY = r"Software\PA_Agent"
_REGISTRY_VALUE = "last_seen_utc"


def license_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".pa_agent"
    path = base / "PA_Agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def license_file_path() -> Path:
    return license_dir() / "license_state.json"


def _registry_read_last_seen() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _REGISTRY_VALUE)
            return int(value)
    except OSError:
        return None


def _registry_write_last_seen(ts: int) -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY) as key:
            winreg.SetValueEx(key, _REGISTRY_VALUE, 0, winreg.REG_DWORD, int(ts))
    except OSError:
        pass


def _registry_clear_last_seen() -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _REGISTRY_VALUE)
    except OSError:
        pass


def _protect(data: bytes) -> str:
    if sys.platform == "win32":
        import win32crypt

        blob = win32crypt.CryptProtectData(data, "PA Agent License", None, None, None, 0)
        return base64.b64encode(blob).decode("ascii")
    from cryptography.fernet import Fernet

    key_path = license_dir() / ".fernet.key"
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
    fernet = Fernet(key_path.read_bytes())
    return fernet.encrypt(data).decode("ascii")


def _unprotect(token: str) -> bytes:
    if sys.platform == "win32":
        import win32crypt

        blob = base64.b64decode(token.encode("ascii"))
        return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1]
    from cryptography.fernet import Fernet

    key_path = license_dir() / ".fernet.key"
    fernet = Fernet(key_path.read_bytes())
    return fernet.decrypt(token.encode("ascii"))


@dataclass(slots=True)
class StoredLicenseState:
    license_token: str
    license_id: str
    machine_id: str
    expires_at: int
    activated_at: int
    last_seen_utc: int

    def to_dict(self) -> dict[str, object]:
        return {
            "license_token": self.license_token,
            "license_id": self.license_id,
            "machine_id": self.machine_id,
            "expires_at": self.expires_at,
            "activated_at": self.activated_at,
            "last_seen_utc": self.last_seen_utc,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "StoredLicenseState":
        return cls(
            license_token=str(data["license_token"]),
            license_id=str(data["license_id"]),
            machine_id=str(data["machine_id"]),
            expires_at=int(data["expires_at"]),
            activated_at=int(data["activated_at"]),
            last_seen_utc=int(data["last_seen_utc"]),
        )


def load_state() -> StoredLicenseState | None:
    path = license_file_path()
    if not path.exists():
        return None
    try:
        protected = path.read_text(encoding="utf-8")
        raw = _unprotect(protected)
        return StoredLicenseState.from_dict(json.loads(raw.decode("utf-8")))
    except Exception:
        return None


def save_state(state: StoredLicenseState) -> None:
    payload = json.dumps(state.to_dict(), ensure_ascii=False).encode("utf-8")
    license_file_path().write_text(_protect(payload), encoding="utf-8")
    _registry_write_last_seen(state.last_seen_utc)


def clear_state() -> None:
    path = license_file_path()
    if path.exists():
        path.unlink()
    _registry_clear_last_seen()


def utc_now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def check_clock_rollback(last_seen_utc: int, now_utc: int | None = None) -> bool:
    """Return True when system clock appears rolled back beyond tolerance."""
    now = utc_now_ts() if now_utc is None else now_utc
    if now + _CLOCK_TOLERANCE_SECONDS < last_seen_utc:
        return True
    return persistent_clock_rollback_detected(now)


def persistent_clock_rollback_detected(now_utc: int | None = None) -> bool:
    now = utc_now_ts() if now_utc is None else now_utc
    registry_seen = _registry_read_last_seen()
    if registry_seen is not None and now + _CLOCK_TOLERANCE_SECONDS < registry_seen:
        return True
    return False


def touch_last_seen(state: StoredLicenseState, now_utc: int | None = None) -> StoredLicenseState:
    now = utc_now_ts() if now_utc is None else now_utc
    if check_clock_rollback(state.last_seen_utc, now):
        raise ValueError("检测到系统时间被回拨，授权已锁定")
    if now > state.last_seen_utc:
        state.last_seen_utc = now
        save_state(state)
        _registry_write_last_seen(now)
    return state
