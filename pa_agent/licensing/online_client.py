"""HTTP client for optional online license verification."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from pa_agent.licensing.client_config import LicenseClientConfig, load_license_client_config

logger = logging.getLogger(__name__)

_TIMEOUT_S = 12


@dataclass(slots=True)
class OnlineLicenseResult:
    ok: bool
    message: str
    expires_at: int | None = None
    server_time: int | None = None
    revoked: bool = False


def _post(path: str, payload: dict[str, Any], config: LicenseClientConfig) -> dict[str, Any]:
    if not config.server_url:
        raise ValueError("未配置授权服务器地址")
    url = f"{config.server_url}{path}"
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "PA-Agent-License/1.0"}
    if config.client_api_key:
        headers["X-Client-Key"] = config.client_api_key
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_response(data: dict[str, Any]) -> OnlineLicenseResult:
    if not data.get("ok"):
        return OnlineLicenseResult(
            ok=False,
            message=str(data.get("message") or "在线授权校验失败"),
            expires_at=data.get("expires_at"),
            server_time=data.get("server_time"),
            revoked=bool(data.get("revoked", False)),
        )
    return OnlineLicenseResult(
        ok=True,
        message=str(data.get("message") or "在线授权有效"),
        expires_at=int(data["expires_at"]) if data.get("expires_at") is not None else None,
        server_time=int(data["server_time"]) if data.get("server_time") is not None else None,
        revoked=bool(data.get("revoked", False)),
    )


def online_activate(token: str, machine_id: str, config: LicenseClientConfig | None = None) -> OnlineLicenseResult:
    config = config or load_license_client_config()
    try:
        data = _post(
            "/api/v1/activate",
            {"token": token, "machine_id": machine_id},
            config,
        )
        return _parse_response(data)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            msg = detail.get("message") or detail.get("detail") or str(exc)
        except Exception:
            msg = f"在线激活失败 (HTTP {exc.code})"
        return OnlineLicenseResult(ok=False, message=str(msg))
    except Exception as exc:
        logger.warning("online activate failed: %s", exc)
        return OnlineLicenseResult(ok=False, message=f"无法连接授权服务器：{exc}")


def online_heartbeat(
    *,
    license_id: str,
    machine_id: str,
    token: str,
    config: LicenseClientConfig | None = None,
) -> OnlineLicenseResult:
    config = config or load_license_client_config()
    try:
        data = _post(
            "/api/v1/heartbeat",
            {
                "license_id": license_id,
                "machine_id": machine_id,
                "token": token,
            },
            config,
        )
        return _parse_response(data)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            msg = detail.get("message") or detail.get("detail") or str(exc)
        except Exception:
            msg = f"在线校验失败 (HTTP {exc.code})"
        return OnlineLicenseResult(ok=False, message=str(msg), revoked=exc.code == 403)
    except Exception as exc:
        logger.warning("online heartbeat failed: %s", exc)
        return OnlineLicenseResult(ok=False, message=f"无法连接授权服务器：{exc}")
