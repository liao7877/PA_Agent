"""Position state model.

A ``PositionState`` represents the lifecycle of a single trade derived from an
analysis decision:

    planned  → 计划单已生成，等待价格触及入场价
    filled   → 价格触及入场价，已持仓（跟踪中）
    closed   → 已出场（触及 TP/SL 或 AI 建议平仓）

Scope (per current product decision): at most one active position per
``symbol|timeframe`` key.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PositionStatus(str, Enum):
    PLANNED = "planned"
    FILLED = "filled"
    CLOSED = "closed"


class PositionState(BaseModel):
    """A tracked trade across analysis rounds."""

    model_config = ConfigDict(extra="ignore")

    status: PositionStatus = PositionStatus.PLANNED
    symbol: str
    timeframe: str

    order_direction: str            # 做多 / 做空
    order_type: str                 # 限价单 / 突破单 / 市价单
    entry_price: float
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None

    entry_basis_bar: Optional[str] = None
    invalidation_condition: Optional[str] = None

    # ── Lifecycle timestamps / provenance ─────────────────────────────────
    planned_at_ms: int = 0
    filled_at_ms: Optional[int] = None
    closed_at_ms: Optional[int] = None
    fill_price: Optional[float] = None
    filled_on_bar_ts: Optional[int] = None
    post_fill_high: Optional[float] = None
    post_fill_low: Optional[float] = None
    first_tracked_bar_ts: Optional[int] = None
    first_tracked_price: Optional[float] = None
    first_tracked_seen: bool = False
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None       # take_profit | stop_loss | ai_close | manual
    opened_at_record_id: Optional[str] = None  # pending json basename

    @property
    def is_long(self) -> bool | None:
        from pa_agent.util.trade_metrics import is_long_direction

        return is_long_direction(self.order_direction)

    @property
    def is_active(self) -> bool:
        return self.status in (PositionStatus.PLANNED, PositionStatus.FILLED)

    def key(self) -> str:
        return f"{self.symbol}|{self.timeframe}"
