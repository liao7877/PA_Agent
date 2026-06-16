"""Notification channel adapters.

Each adapter renders a :class:`NotificationMessage` into a channel-specific
HTTP request and POSTs it. Uses the standard library ``urllib`` only, so the
package adds no third-party dependency.

Supported channels:
- :class:`DingTalkChannel` — 钉钉群机器人 webhook（支持加签）。
- :class:`WeChatChannel` — 通用 JSON webhook，兼容 Bark / Server酱 /
  企业微信群机器人 等以 ``{"title", "text"}`` / markdown 形式接收的服务。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

from pa_agent.notification.events import NotificationMessage


@dataclass(slots=True)
class ChannelResult:
    ok: bool
    status: int | None = None
    error: str = ""


class Channel(ABC):
    """Base channel adapter."""

    name: str = "channel"

    def __init__(self, *, timeout_s: int = 10) -> None:
        self._timeout_s = timeout_s

    @abstractmethod
    def _build_request(self, message: NotificationMessage) -> urllib.request.Request:
        """Return the prepared HTTP request for *message*."""

    def send(self, message: NotificationMessage) -> ChannelResult:
        try:
            req = self._build_request(message)
        except Exception as exc:  # noqa: BLE001
            return ChannelResult(ok=False, error=f"build request failed: {exc}")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                body = resp.read().decode("utf-8", errors="replace")
                return self._interpret_response(status, body)
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            return ChannelResult(ok=False, status=exc.code, error=f"HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001
            return ChannelResult(ok=False, error=str(exc))

    def _interpret_response(self, status: int, body: str) -> ChannelResult:
        ok = 200 <= int(status) < 300
        return ChannelResult(ok=ok, status=status, error="" if ok else body[:200])

    @staticmethod
    def _post_json(url: str, payload: dict) -> urllib.request.Request:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )


class DingTalkChannel(Channel):
    """钉钉群机器人 webhook (markdown message, optional 加签)."""

    name = "dingtalk"

    def __init__(self, *, webhook: str, secret: str = "", timeout_s: int = 10) -> None:
        super().__init__(timeout_s=timeout_s)
        self._webhook = webhook
        self._secret = secret or ""

    def _signed_url(self) -> str:
        if not self._secret:
            return self._webhook
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self._secret}"
        digest = hmac.new(
            self._secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
        sep = "&" if "?" in self._webhook else "?"
        return f"{self._webhook}{sep}timestamp={timestamp}&sign={sign}"

    @staticmethod
    def _action_card_text(message: NotificationMessage) -> str:
        """Merge title into actionCard body.

        DingTalk shows ``title`` in the chat list preview but only ``text`` when
        the user opens the message — prepend the title so detail view matches.
        """
        title = (message.title or "").strip()
        body = (message.text or "").strip()
        if not title:
            return body
        if not body:
            return f"### {title}"
        first_line = body.split("\n", 1)[0].strip()
        if first_line == title or first_line.lstrip("#").strip() == title:
            return body
        return f"### {title}\n\n{body}"

    def _build_request(self, message: NotificationMessage) -> urllib.request.Request:
        # ActionCard renders as a compact card in DingTalk (closer to the GUI panel).
        payload = {
            "msgtype": "actionCard",
            "actionCard": {
                "title": message.title,
                "text": self._action_card_text(message),
            },
        }
        return self._post_json(self._signed_url(), payload)

    def _interpret_response(self, status: int, body: str) -> ChannelResult:
        # DingTalk returns HTTP 200 with errcode in body even on logical failure.
        try:
            data = json.loads(body)
            errcode = int(data.get("errcode", 0))
            if errcode != 0:
                return ChannelResult(
                    ok=False, status=status,
                    error=str(data.get("errmsg") or f"errcode={errcode}"),
                )
        except (ValueError, TypeError):
            pass
        return super()._interpret_response(status, body)


class WeChatChannel(Channel):
    """Generic JSON webhook for WeChat-style push (Bark / Server酱 / 企业微信).

    Posts ``{"title", "text", "body", "content"}`` so the same payload works
    across Bark (title/body), Server酱 (title/desp-like) and 企业微信 markdown
    consumers that read ``content``.
    """

    name = "wechat"

    def __init__(self, *, webhook: str, timeout_s: int = 10) -> None:
        super().__init__(timeout_s=timeout_s)
        self._webhook = webhook

    def _build_request(self, message: NotificationMessage) -> urllib.request.Request:
        body = (message.plain_text or message.text).strip()
        combined = f"{message.title}\n{body}"
        payload = {
            "title": message.title,
            "text": body,
            "body": body,
            "content": combined,
            "msgtype": "text",
        }
        return self._post_json(self._webhook, payload)
