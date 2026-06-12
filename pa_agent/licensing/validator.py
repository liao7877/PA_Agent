"""License validation and activation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pa_agent.licensing import crypto
from pa_agent.licensing.client_config import LicenseClientConfig, load_license_client_config
from pa_agent.licensing.machine_id import get_machine_fingerprint
from pa_agent.licensing.online_client import online_activate, online_heartbeat
from pa_agent.licensing.packaged import is_packaged_build
from pa_agent.licensing.trusted_time import clock_skew_exceeds_tolerance
from pa_agent.licensing.storage import (
    StoredLicenseState,
    check_clock_rollback,
    clear_state,
    load_state,
    persistent_clock_rollback_detected,
    save_state,
    touch_last_seen,
    utc_now_ts,
)


class LicenseStatus(str, Enum):
    VALID = "valid"
    MISSING = "missing"
    EXPIRED = "expired"
    INVALID = "invalid"
    MACHINE_MISMATCH = "machine_mismatch"
    CLOCK_ROLLBACK = "clock_rollback"
    VERSION_MISMATCH = "version_mismatch"
    ONLINE_DENIED = "online_denied"
    ONLINE_UNAVAILABLE = "online_unavailable"


@dataclass(slots=True)
class LicenseInfo:
    status: LicenseStatus
    message: str
    license_id: str | None = None
    expires_at: int | None = None
    days_remaining: int | None = None
    machine_id: str | None = None
    online_mode: bool = False

    @property
    def ok(self) -> bool:
        return self.status is LicenseStatus.VALID


_IAT_TOLERANCE_SECONDS = 300


def _dev_license_bypass_enabled() -> bool:
    """Skip activation when running from source; packaged builds still require a license."""
    return not is_packaged_build()


def _offline_time_checks(now: int) -> LicenseInfo | None:
    """Extra offline anti-tamper checks for packaged builds."""
    if not is_packaged_build():
        return None
    if clock_skew_exceeds_tolerance(now):
        return LicenseInfo(
            LicenseStatus.CLOCK_ROLLBACK,
            "系统时间与网络时间偏差过大，请开启网络并同步系统时间",
        )
    return None


def _payload_checks(payload: dict, signature: bytes) -> LicenseInfo:
    if int(payload.get("v", 0)) != crypto.LICENSE_VERSION:
        return LicenseInfo(LicenseStatus.VERSION_MISMATCH, "激活码版本不受支持")

    public_key = crypto.load_public_key()
    if not crypto.verify_payload(public_key, payload, signature):
        return LicenseInfo(LicenseStatus.INVALID, "激活码签名无效，可能被篡改")

    exp = int(payload["exp"])
    now = utc_now_ts()
    iat = int(payload.get("iat", 0))
    if iat and now + _IAT_TOLERANCE_SECONDS < iat:
        return LicenseInfo(
            LicenseStatus.CLOCK_ROLLBACK,
            "系统时间异常（早于激活码签发时间），请同步网络时间后重试",
        )
    skew_info = _offline_time_checks(now)
    if skew_info is not None:
        return skew_info
    if now > exp:
        return LicenseInfo(
            LicenseStatus.EXPIRED,
            "授权已过期，请联系供应商续期",
            license_id=str(payload.get("lid", "")),
            expires_at=exp,
        )

    bound_mid = payload.get("mid")
    local_mid = get_machine_fingerprint()
    if bound_mid and str(bound_mid).upper() != local_mid:
        return LicenseInfo(
            LicenseStatus.MACHINE_MISMATCH,
            "此激活码已绑定其它设备，无法在本机使用",
            machine_id=local_mid,
        )

    remaining = max(0, (exp - now + 86399) // 86400)
    return LicenseInfo(
        LicenseStatus.VALID,
        "授权有效",
        license_id=str(payload.get("lid", "")),
        expires_at=exp,
        days_remaining=int(remaining),
        machine_id=local_mid,
    )


class LicenseValidator:
    def __init__(self, client_config: LicenseClientConfig | None = None) -> None:
        self._config_override = client_config

    def _client_config(self) -> LicenseClientConfig:
        return self._config_override or load_license_client_config()

    def current_machine_id(self) -> str:
        return get_machine_fingerprint()

    def _online_check(
        self,
        *,
        token: str,
        license_id: str,
        activate: bool,
    ) -> LicenseInfo | None:
        cfg = self._client_config()
        if not cfg.active:
            return None

        machine_id = get_machine_fingerprint()
        if activate:
            result = online_activate(token, machine_id, cfg)
        else:
            result = online_heartbeat(
                license_id=license_id,
                machine_id=machine_id,
                token=token,
                config=cfg,
            )

        if result.revoked:
            clear_state()
            return LicenseInfo(
                LicenseStatus.ONLINE_DENIED,
                result.message or "授权已被服务器吊销",
                license_id=license_id,
                online_mode=True,
            )
        if not result.ok:
            status = LicenseStatus.ONLINE_DENIED if result.revoked else LicenseStatus.ONLINE_UNAVAILABLE
            return LicenseInfo(status, result.message, license_id=license_id, online_mode=True)

        if result.expires_at is not None and utc_now_ts() > int(result.expires_at):
            clear_state()
            return LicenseInfo(
                LicenseStatus.EXPIRED,
                "授权已过期（服务器校验）",
                license_id=license_id,
                expires_at=int(result.expires_at),
                online_mode=True,
            )
        return None

    def validate_token(self, token: str) -> LicenseInfo:
        try:
            payload, signature = crypto.decode_license_token(token)
        except Exception:
            return LicenseInfo(LicenseStatus.INVALID, "激活码格式无效")
        return _payload_checks(payload, signature)

    def activate(self, token: str) -> LicenseInfo:
        if persistent_clock_rollback_detected():
            return LicenseInfo(
                LicenseStatus.CLOCK_ROLLBACK,
                "检测到系统时间被回拨，请恢复正确时间后重试",
            )

        info = self.validate_token(token)
        if not info.ok:
            return info

        payload, _ = crypto.decode_license_token(token)
        license_id = str(payload["lid"])
        online_info = self._online_check(token=token.strip(), license_id=license_id, activate=True)
        if online_info is not None and not online_info.ok:
            return online_info

        now = utc_now_ts()
        state = StoredLicenseState(
            license_token=token.strip(),
            license_id=license_id,
            machine_id=get_machine_fingerprint(),
            expires_at=int(payload["exp"]),
            activated_at=now,
            last_seen_utc=now,
        )
        save_state(state)
        info.online_mode = self._client_config().active
        return info

    def check(self) -> LicenseInfo:
        if _dev_license_bypass_enabled():
            return LicenseInfo(LicenseStatus.VALID, "开发模式：已跳过授权检查")

        state = load_state()
        if state is None:
            return LicenseInfo(LicenseStatus.MISSING, "尚未激活，请输入激活码")

        if check_clock_rollback(state.last_seen_utc):
            return LicenseInfo(LicenseStatus.CLOCK_ROLLBACK, "检测到系统时间被回拨，请恢复正确时间后重试")

        now = utc_now_ts()
        skew_info = _offline_time_checks(now)
        if skew_info is not None:
            return skew_info

        info = self.validate_token(state.license_token)
        if not info.ok:
            if info.status in {LicenseStatus.EXPIRED, LicenseStatus.INVALID, LicenseStatus.MACHINE_MISMATCH}:
                clear_state()
            return info

        online_info = self._online_check(
            token=state.license_token,
            license_id=state.license_id,
            activate=False,
        )
        if online_info is not None and not online_info.ok:
            return online_info

        try:
            touch_last_seen(state)
        except ValueError as exc:
            return LicenseInfo(LicenseStatus.CLOCK_ROLLBACK, str(exc))

        info.online_mode = self._client_config().active
        return info

    @staticmethod
    def format_expiry(expires_at: int | None) -> str:
        if expires_at is None:
            return "—"
        dt = datetime.fromtimestamp(expires_at, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
