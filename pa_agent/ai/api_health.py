"""API connectivity probe and API-error classification helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pa_agent.config.settings import AIProviderSettings


@dataclass(frozen=True)
class ApiHealthResult:
    ok: bool
    message: str
    latency_ms: float = 0.0
    reasoning_chars: int = 0
    content_chars: int = 0


def is_api_error(exc: Exception) -> bool:
    """Return True when *exc* looks like an upstream API / network failure."""
    from pa_agent.ai.deepseek_client import CancelledError

    if isinstance(exc, CancelledError):
        return False

    try:
        import openai  # type: ignore[import]

        if isinstance(
            exc,
            (
                openai.APITimeoutError,
                openai.APIConnectionError,
                openai.APIStatusError,
            ),
        ):
            return True
    except ImportError:
        pass

    try:
        import httpx  # type: ignore[import]

        if isinstance(
            exc,
            (
                httpx.ReadError,
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.RemoteProtocolError,
            ),
        ):
            return True
    except ImportError:
        pass

    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, TimeoutError)):
        return True
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (
        10054,
        10053,
        10060,
    ):
        return True

    cause = exc.__cause__
    if cause is not None and cause is not exc:
        return is_api_error(cause)
    return False


def is_api_exception_dict(exc: dict[str, Any] | None) -> bool:
    """Return True when an analysis-record exception payload is API-related."""
    if not isinstance(exc, dict):
        return False
    exc_type = str(exc.get("type") or "").strip().lower()
    if exc_type in {"network_error", "api_error"}:
        return True
    category = str(exc.get("category") or "").strip().lower()
    return category in {"network_error", "api_error"}


def api_exception_payload(
    *,
    message: str,
    stage: str = "",
    source: str = "analysis",
) -> dict[str, str]:
    return {
        "type": "api_error",
        "stage": stage,
        "source": source,
        "message": message,
    }


def check_api_health(
    provider: "AIProviderSettings",
    *,
    timeout_s: float = 45.0,
) -> ApiHealthResult:
    """Probe provider connectivity with a minimal chat completion."""
    from pa_agent.ai.deepseek_client import DeepSeekClient

    client = DeepSeekClient(settings=provider)
    try:
        reply = client.stream_chat(
            [{"role": "user", "content": "ping"}],
            thinking=provider.thinking,
            reasoning_effort=provider.reasoning_effort,
            timeout_s=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        return ApiHealthResult(ok=False, message=str(exc).strip() or repr(exc))

    return ApiHealthResult(
        ok=True,
        message="API 调用成功",
        latency_ms=reply.latency_ms,
        reasoning_chars=len(reply.reasoning_content or ""),
        content_chars=len(reply.content or ""),
    )
