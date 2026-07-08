"""查询 ModelScope API-Inference 单模型与用户总额度。

通过一次最小 chat/completions 请求读取响应头中的限额信息：
  - modelscope-ratelimit-requests-limit / -remaining        用户当日总额度
  - modelscope-ratelimit-model-requests-limit / -remaining  单模型当日额度

注意：查询本身会消耗 1 次 API 调用额度。

用法示例：
  python tools/check_modelscope_quota.py
  python tools/check_modelscope_quota.py --settings config/settings.json
  python tools/check_modelscope_quota.py --api-key ms-xxx --model deepseek-ai/DeepSeek-V4-Pro
  python tools/check_modelscope_quota.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://api-inference.modelscope.cn/v1"
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4-Pro"
DEFAULT_SETTINGS = Path(__file__).resolve().parents[1] / "config" / "settings.json"
TIMEOUT_SEC = 90

HEADER_USER_LIMIT = "modelscope-ratelimit-requests-limit"
HEADER_USER_REMAINING = "modelscope-ratelimit-requests-remaining"
HEADER_MODEL_LIMIT = "modelscope-ratelimit-model-requests-limit"
HEADER_MODEL_REMAINING = "modelscope-ratelimit-model-requests-remaining"


@dataclass(frozen=True)
class QuotaInfo:
    base_url: str
    model: str
    user_limit: int | None
    user_remaining: int | None
    user_used: int | None
    model_limit: int | None
    model_remaining: int | None
    model_used: int | None
    http_status: int
    request_id: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.user_limit is not None and self.model_limit is not None


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _used(limit: int | None, remaining: int | None) -> int | None:
    if limit is None or remaining is None:
        return None
    return max(limit - remaining, 0)


def _load_settings(path: Path) -> tuple[str, str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    provider = data.get("provider") or {}
    api_key = str(provider.get("api_key") or "").strip()
    base_url = str(provider.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    model = str(provider.get("model") or DEFAULT_MODEL).strip()
    if not api_key:
        raise ValueError(f"配置文件中未找到 provider.api_key: {path}")
    return api_key, base_url, model


def _extract_headers(headers) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        out[key.lower()] = value
    return out


def _extract_request_id(body_text: str) -> str | None:
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        req_id = payload.get("request_id")
        if isinstance(req_id, str) and req_id:
            return req_id
        err = payload.get("error")
        if isinstance(err, dict):
            req_id = err.get("request_id")
            if isinstance(req_id, str) and req_id:
                return req_id
    return None


def _extract_error_message(body_text: str) -> str | None:
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return body_text[:300] if body_text else None
    if not isinstance(payload, dict):
        return None
    err = payload.get("error")
    if isinstance(err, dict):
        msg = err.get("message")
        if isinstance(msg, str) and msg:
            return msg
    return None


def query_quota(
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout: int = TIMEOUT_SEC,
) -> QuotaInfo:
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body_text = resp.read().decode("utf-8", errors="replace")
            headers = _extract_headers(resp.headers)
            status = resp.status
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        headers = _extract_headers(exc.headers)
        status = exc.code
    except urllib.error.URLError as exc:
        return QuotaInfo(
            base_url=base_url,
            model=model,
            user_limit=None,
            user_remaining=None,
            user_used=None,
            model_limit=None,
            model_remaining=None,
            model_used=None,
            http_status=0,
            error_message=f"网络请求失败: {exc.reason}",
        )

    user_limit = _parse_int(headers.get(HEADER_USER_LIMIT))
    user_remaining = _parse_int(headers.get(HEADER_USER_REMAINING))
    model_limit = _parse_int(headers.get(HEADER_MODEL_LIMIT))
    model_remaining = _parse_int(headers.get(HEADER_MODEL_REMAINING))

    return QuotaInfo(
        base_url=base_url,
        model=model,
        user_limit=user_limit,
        user_remaining=user_remaining,
        user_used=_used(user_limit, user_remaining),
        model_limit=model_limit,
        model_remaining=model_remaining,
        model_used=_used(model_limit, model_remaining),
        http_status=status,
        request_id=_extract_request_id(body_text),
        error_message=_extract_error_message(body_text) if not (user_limit and model_limit) else None,
    )


def _fmt_quota(used: int | None, remaining: int | None, limit: int | None) -> str:
    if limit is None or remaining is None:
        return "未知"
    used_text = used if used is not None else max(limit - remaining, 0)
    return f"{used_text}/{limit}（剩余 {remaining}）"


def _print_human(info: QuotaInfo) -> None:
    print("ModelScope API 额度查询")
    print("=" * 48)
    print(f"Base URL : {info.base_url}")
    print(f"Model ID : {info.model}")
    print(f"HTTP     : {info.http_status}")
    if info.request_id:
        print(f"Request  : {info.request_id}")
    print()
    print("【用户总额度（当日）】")
    print(f"  限额 : {info.user_limit if info.user_limit is not None else '未知'}")
    print(f"  剩余 : {info.user_remaining if info.user_remaining is not None else '未知'}")
    print(f"  已用 : {_fmt_quota(info.user_used, info.user_remaining, info.user_limit)}")
    print()
    print("【单模型额度（当日）】")
    print(f"  限额 : {info.model_limit if info.model_limit is not None else '未知'}")
    print(f"  剩余 : {info.model_remaining if info.model_remaining is not None else '未知'}")
    print(f"  已用 : {_fmt_quota(info.model_used, info.model_remaining, info.model_limit)}")
    print()
    print("说明：")
    print("  - 额度每日 UTC+8 00:00 重置，不支持跨日累计。")
    print("  - 单模型限额会随平台资源动态调整。")
    print("  - 本次查询已消耗 1 次 API 调用。")
    if info.error_message:
        print()
        print(f"接口提示: {info.error_message}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询 ModelScope API-Inference 额度")
    parser.add_argument("--api-key", default="", help="ModelScope Token（也可用环境变量 MODELSCOPE_API_KEY）")
    parser.add_argument("--base-url", default="", help=f"API Base URL，默认 {DEFAULT_BASE_URL}")
    parser.add_argument("--model", default="", help=f"模型 ID，默认 {DEFAULT_MODEL}")
    parser.add_argument(
        "--settings",
        default="",
        help=f"从 JSON 配置读取 provider 信息，默认 {DEFAULT_SETTINGS}",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SEC, help="请求超时秒数")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    api_key = (args.api_key or os.environ.get("MODELSCOPE_API_KEY", "")).strip()
    base_url = (args.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    model = (args.model or DEFAULT_MODEL).strip()

    if not api_key:
        settings_path = Path(args.settings) if args.settings else DEFAULT_SETTINGS
        try:
            loaded_key, loaded_base, loaded_model = _load_settings(settings_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"错误: 无法读取配置 {settings_path}: {exc}", file=sys.stderr)
            return 1
        api_key = loaded_key
        if not args.base_url:
            base_url = loaded_base
        if not args.model:
            model = loaded_model

    info = query_quota(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=args.timeout,
    )

    if args.json:
        print(json.dumps(asdict(info), ensure_ascii=False, indent=2))
    else:
        _print_human(info)

    if not info.ok:
        if info.error_message and not args.json:
            pass
        elif not info.error_message:
            print("错误: 响应中未找到额度相关响应头。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
