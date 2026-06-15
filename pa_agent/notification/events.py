"""Notification event scenes and message model.

These are framework-agnostic data structures (no PyQt / no HTTP) so they can
be unit-tested in isolation and reused by both the decision pipeline and the
position tracker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NotificationEvent(str, Enum):
    """A notifiable scene. Each maps to one per-scene toggle in settings."""

    NEW_ORDER = "new_order"          # 产生新的下单决策（入场/止盈/止损）
    ENTRY_FILLED = "entry_filled"    # 计划单被市场触及、确认入场成交
    EXIT = "exit"                    # 持仓出场（止盈/止损/AI 平仓）
    MANAGE = "manage"                # 持仓管理调整（移动止损/止盈）
    NO_TRADE = "no_trade"            # 观望/不下单结论
    ERROR = "error"                  # 分析失败/异常
    API_ERROR = "api_error"          # AI API 调用失败（网络/鉴权/限流等）

    @property
    def setting_attr(self) -> str:
        """Name of the matching ``NotificationSettings`` boolean field."""
        return f"notify_{self.value}"


@dataclass(slots=True)
class NotificationMessage:
    """A channel-agnostic message.

    Adapters render this into their own payloads. ``title`` is used by
    channels that support it (Bark / DingTalk markdown); ``text`` is the
    plain-text / markdown body used everywhere.
    """

    event: NotificationEvent
    title: str
    text: str
    #: Plain-text body for channels that do not render markdown (WeChat/Bark).
    plain_text: str = ""
    #: Optional structured fields for richer rendering / debugging.
    fields: dict = field(default_factory=dict)
