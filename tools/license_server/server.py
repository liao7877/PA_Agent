#!/usr/bin/env python3
"""Trading Agent online license server (vendor self-hosted).

Usage:
  pip install fastapi uvicorn
  python tools/license_server/server.py --public-key pa_agent/licensing/public_key.pem

Environment:
  PA_LICENSE_API_KEY   optional client API key (X-Client-Key header)
  PA_LICENSE_DB        sqlite path, default tools/license_server/licenses.db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from pa_agent.licensing import crypto
from pa_agent.licensing.validator import LicenseStatus, _payload_checks

DEFAULT_DB = Path(__file__).resolve().parent / "licenses.db"
API_KEY = os.environ.get("PA_LICENSE_API_KEY", "").strip()


class ActivateRequest(BaseModel):
    token: str
    machine_id: str = Field(min_length=8, max_length=64)


class HeartbeatRequest(BaseModel):
    license_id: str
    machine_id: str = Field(min_length=8, max_length=64)
    token: str


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def _now() -> int:
    return int(time.time())


@contextmanager
def _db(path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activations (
                license_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                activated_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL
            )
            """
        )
        conn.commit()
        yield conn
    finally:
        conn.close()


def _auth(client_key: str | None) -> None:
    if API_KEY and client_key != API_KEY:
        raise HTTPException(status_code=401, detail="无效的客户端密钥")


def _validate_token(token: str, machine_id: str):
    try:
        payload, signature = crypto.decode_license_token(token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"激活码格式无效: {exc}") from exc
    info = _payload_checks(payload, signature)
    if info.status is LicenseStatus.MACHINE_MISMATCH:
        raise HTTPException(status_code=403, detail=info.message)
    if not info.ok:
        raise HTTPException(status_code=403, detail=info.message)
    bound_mid = payload.get("mid")
    if bound_mid and str(bound_mid).upper() != machine_id.upper():
        raise HTTPException(status_code=403, detail="激活码与机器码不匹配")
    return payload, info


def create_app(db_path: Path, public_key_path: Path | None = None) -> FastAPI:
    if public_key_path is not None:
        # Allow server to use a custom public key path via monkeypatch at import time.
        pem = public_key_path.read_bytes()

        def _load() -> bytes:
            return pem

        crypto.load_public_key_pem = _load  # type: ignore[method-assign]

    app = FastAPI(title="Trading Agent License Server", version="1.0")

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "server_time": _now()}

    @app.post("/api/v1/activate")
    def activate(
        body: ActivateRequest,
        x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
    ) -> dict[str, Any]:
        _auth(x_client_key)
        payload, info = _validate_token(body.token, body.machine_id)
        license_id = str(payload["lid"])
        now = _now()
        th = _token_hash(body.token)
        with _db(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM activations WHERE license_id = ?", (license_id,)
            ).fetchone()
            if row and int(row["revoked"]):
                raise HTTPException(status_code=403, detail="授权已被吊销")
            if row and row["machine_id"] != body.machine_id:
                raise HTTPException(status_code=403, detail="此授权已绑定其它设备")
            if row:
                conn.execute(
                    "UPDATE activations SET last_seen_at=?, expires_at=?, token_hash=? WHERE license_id=?",
                    (now, int(payload["exp"]), th, license_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO activations
                    (license_id, token_hash, machine_id, expires_at, revoked, activated_at, last_seen_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                    """,
                    (license_id, th, body.machine_id, int(payload["exp"]), now, now),
                )
            conn.commit()
        return {
            "ok": True,
            "message": "在线激活成功",
            "license_id": license_id,
            "expires_at": int(payload["exp"]),
            "server_time": now,
        }

    @app.post("/api/v1/heartbeat")
    def heartbeat(
        body: HeartbeatRequest,
        x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
    ) -> dict[str, Any]:
        _auth(x_client_key)
        payload, info = _validate_token(body.token, body.machine_id)
        if str(payload["lid"]) != body.license_id:
            raise HTTPException(status_code=403, detail="授权 ID 不匹配")
        now = _now()
        th = _token_hash(body.token)
        with _db(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM activations WHERE license_id = ?", (body.license_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=403, detail="未在服务器注册，请重新激活")
            if int(row["revoked"]):
                return {
                    "ok": False,
                    "revoked": True,
                    "message": "授权已被吊销",
                    "server_time": now,
                }
            if row["machine_id"] != body.machine_id or row["token_hash"] != th:
                raise HTTPException(status_code=403, detail="授权与设备不匹配")
            conn.execute(
                "UPDATE activations SET last_seen_at=?, expires_at=? WHERE license_id=?",
                (now, int(payload["exp"]), body.license_id),
            )
            conn.commit()
        if not info.ok:
            raise HTTPException(status_code=403, detail=info.message)
        return {
            "ok": True,
            "message": "在线授权有效",
            "expires_at": int(payload["exp"]),
            "server_time": now,
            "revoked": False,
        }

    @app.post("/api/v1/revoke")
    def revoke(
        license_id: str,
        x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
    ) -> dict[str, Any]:
        _auth(x_client_key)
        with _db(db_path) as conn:
            conn.execute("UPDATE activations SET revoked=1 WHERE license_id=?", (license_id,))
            conn.commit()
        return {"ok": True, "license_id": license_id, "revoked": True}

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trading Agent license server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--public-key", default=str(ROOT / "pa_agent" / "licensing" / "public_key.pem"))
    args = parser.parse_args(argv)

    import uvicorn

    app = create_app(Path(args.db), Path(args.public_key))
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
