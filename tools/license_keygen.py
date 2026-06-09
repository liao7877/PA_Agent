#!/usr/bin/env python3
"""Vendor-only CLI to generate license keys for PA Agent."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pa_agent.licensing.issuer import (
    DEFAULT_PRIVATE_KEY,
    DEFAULT_PUBLIC_KEY,
    generate_keypair,
    issue_license,
    verify_license_token,
)
from pa_agent.licensing.validator import LicenseValidator


def cmd_generate_keys(args: argparse.Namespace) -> int:
    private_path, public_path = generate_keypair(
        private_path=Path(args.output_dir) / "license_private.pem",
        public_path=Path(args.public_key or DEFAULT_PUBLIC_KEY),
    )
    print(f"私钥（妥善保管，勿分发）: {private_path}")
    print(f"公钥（随程序打包）: {public_path}")
    return 0


def cmd_issue(args: argparse.Namespace) -> int:
    private_path = Path(args.private_key or DEFAULT_PRIVATE_KEY)
    expires = None
    if args.expires:
        expires = datetime.fromisoformat(args.expires).replace(tzinfo=timezone.utc)
    try:
        issued = issue_license(
            private_key_path=private_path,
            days=args.days,
            expires=expires,
            machine=args.machine,
            license_id=args.license_id,
            holder=args.holder or "",
        )
    except FileNotFoundError as exc:
        print(exc)
        print("请先运行: python tools/license_keygen.py generate-keys")
        return 1

    print("激活码:")
    print(issued.token)
    print()
    print(f"授权 ID: {issued.license_id}")
    print(f"到期时间(UTC): {issued.expires_at_utc}")
    print(f"绑定机器: {issued.machine_label}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    info = verify_license_token(args.token)
    print(info.status.value)
    print(info.message)
    if info.expires_at:
        print(f"到期: {LicenseValidator.format_expiry(info.expires_at)}")
    return 0 if info.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PA Agent 激活码生成工具（仅供应商使用）")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate-keys", help="生成新的 Ed25519 密钥对")
    gen.add_argument("--output-dir", default=str(DEFAULT_PRIVATE_KEY.parent))
    gen.add_argument("--public-key", default=str(DEFAULT_PUBLIC_KEY))
    gen.set_defaults(func=cmd_generate_keys)

    issue = sub.add_parser("issue", help="签发激活码")
    issue.add_argument("--days", type=int, default=30, help="有效天数（默认 30）")
    issue.add_argument("--expires", help="到期时间 ISO 格式，例如 2026-12-31")
    issue.add_argument("--machine", default="local", help="local / any / 16位机器指纹")
    issue.add_argument("--license-id", help="自定义授权 ID")
    issue.add_argument("--holder", help="客户备注")
    issue.add_argument("--private-key", default=str(DEFAULT_PRIVATE_KEY))
    issue.set_defaults(func=cmd_issue)

    verify = sub.add_parser("verify", help="验证激活码")
    verify.add_argument("token")
    verify.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
