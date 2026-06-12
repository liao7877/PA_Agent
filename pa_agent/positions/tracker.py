"""PositionTracker — lifecycle state machine + fill/exit detection.

Responsibilities:
- Derive a ``planned`` position from a fresh analysis decision (NEW_ORDER).
- Detect fill: price touches ``entry_price`` → ``filled`` (+ ENTRY_FILLED notify).
- Detect exit: price touches TP/SL → ``closed`` (+ EXIT notify).
- Apply a new analysis decision against an *existing* active position:
    * 方向反转                                → close + open opposite (EXIT notify)
    * position_action=平仓                    → close (ai_close, EXIT notify)
    * position_action=调整                    → apply TP/SL + manage (MANAGE notify)
    * position_action=持有 / 无该字段           → no-op on filled positions
    * TP/SL 改变                              → manage (MANAGE notify)

All price comparisons use bar high/low so intrabar touches are caught.
Detection is intentionally simple/software-only (no broker fills).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from pa_agent.positions.decision_fields import (
    is_position_adjust,
    is_position_close,
    position_advice_text,
)
from pa_agent.positions.model import PositionState, PositionStatus
from pa_agent.positions.store import PositionStore
from pa_agent.util.trade_metrics import is_long_direction

logger = logging.getLogger("pa_agent")

_NO_ORDER_TEXT = "不下单"
_ORDER_TYPES = ("限价单", "突破单", "市价单")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PositionTracker:
    """Tracks one active position per symbol|timeframe.

    Parameters
    ----------
    store:
        Persistence backend.
    notifier:
        Optional object exposing ``notify(NotificationMessage)``. May be None.
    """

    def __init__(self, *, store: PositionStore | None = None, notifier: Any = None) -> None:
        self._store = store or PositionStore()
        self._notifier = notifier

    @property
    def store(self) -> PositionStore:
        return self._store

    def get_active(self, symbol: str, timeframe: str) -> Optional[PositionState]:
        return self._store.get_active(symbol, timeframe)

    # ── Decision ingestion ─────────────────────────────────────────────────
    def apply_decision(
        self,
        *,
        symbol: str,
        timeframe: str,
        decision: dict,
        record_id: str | None = None,
        current_price: float | None = None,
        fill_bar_ts: int | None = None,
    ) -> Optional[PositionState]:
        """Reconcile a new stage-2 decision with the current active position.

        Returns the resulting active position (or None when none is active).
        """
        inner = decision.get("decision", decision) if isinstance(decision, dict) else {}
        order_type = str(inner.get("order_type") or _NO_ORDER_TEXT)
        existing = self._store.get_active(symbol, timeframe)

        if existing is None:
            # No active position: a tradeable decision opens a new planned order.
            if order_type in _ORDER_TYPES:
                return self._open_planned(
                    symbol=symbol,
                    timeframe=timeframe,
                    inner=inner,
                    record_id=record_id,
                    fill_bar_ts=fill_bar_ts,
                )
            return None

        # An active position exists → manage it instead of re-deciding entry.
        return self._manage_existing(
            existing, inner, order_type, current_price=current_price
        )

    def _open_planned(
        self,
        *,
        symbol: str,
        timeframe: str,
        inner: dict,
        record_id: str | None,
        fill_bar_ts: int | None = None,
    ) -> Optional[PositionState]:
        entry = _to_float(inner.get("entry_price"))
        if entry is None:
            return None
        position = PositionState(
            status=PositionStatus.PLANNED,
            symbol=symbol,
            timeframe=timeframe,
            order_direction=str(inner.get("order_direction") or ""),
            order_type=inner.get("order_type") or "",
            entry_price=entry,
            take_profit_price=_to_float(inner.get("take_profit_price")),
            stop_loss_price=_to_float(inner.get("stop_loss_price")),
            entry_basis_bar=inner.get("entry_basis_bar"),
            invalidation_condition=inner.get("invalidation_condition"),
            planned_at_ms=_now_ms(),
            opened_at_record_id=record_id,
        )
        # 市价单 is considered immediately filled at entry.
        if position.order_type == "市价单":
            position.status = PositionStatus.FILLED
            position.filled_at_ms = position.planned_at_ms
            position.fill_price = entry
            if fill_bar_ts is not None:
                position.filled_on_bar_ts = int(fill_bar_ts)
        self._store.upsert_active(position)
        logger.info("Position opened (%s) %s %s @ %s",
                    position.status.value, symbol, timeframe, entry)
        return position

    def _manage_existing(
        self,
        existing: PositionState,
        inner: dict,
        order_type: str,
        *,
        current_price: float | None = None,
    ) -> Optional[PositionState]:
        # 1) 方向反转 → 先平再开反向计划单
        new_dir = is_long_direction(inner.get("order_direction"))
        cur_dir = existing.is_long
        reversed_dir = (
            order_type in _ORDER_TYPES
            and new_dir is not None
            and cur_dir is not None
            and new_dir != cur_dir
        )

        if existing.status == PositionStatus.FILLED and reversed_dir:
            exit_px = self._resolve_exit_price(existing, current_price)
            self._close(
                existing,
                exit_price=exit_px,
                reason="ai_close",
                notify_reason="AI 建议平仓（方向反转）",
            )
            return self._open_planned(
                symbol=existing.symbol,
                timeframe=existing.timeframe,
                inner=inner,
                record_id=existing.opened_at_record_id,
            )

        # 2) 已持仓 + position_action=平仓（结构化字段，不解析 reasoning 关键词）
        if existing.status == PositionStatus.FILLED and is_position_close(inner):
            exit_px = self._resolve_exit_price(existing, current_price)
            self._close(
                existing,
                exit_price=exit_px,
                reason="ai_close",
                notify_reason="AI 建议平仓",
            )
            return None

        if existing.status == PositionStatus.PLANNED and order_type == _NO_ORDER_TEXT:
            # Planned (not yet filled) and AI no longer wants the trade → drop it.
            self._store.clear_active(existing.symbol, existing.timeframe)
            logger.info("Planned position cancelled by new decision: %s %s",
                        existing.symbol, existing.timeframe)
            return None

        # 3) TP/SL 调整（持仓管理）；position_action=调整 或同向下单三价变化
        new_tp = _to_float(inner.get("take_profit_price"))
        new_sl = _to_float(inner.get("stop_loss_price"))
        changes: list[str] = []
        if new_tp is not None and new_tp != existing.take_profit_price:
            changes.append(f"止盈 {existing.take_profit_price}→{new_tp}")
            existing.take_profit_price = new_tp
        if new_sl is not None and new_sl != existing.stop_loss_price:
            changes.append(f"止损 {existing.stop_loss_price}→{new_sl}")
            existing.stop_loss_price = new_sl
        if changes:
            self._store.upsert_active(existing)
            self._notify_manage(existing, "；".join(changes))
            return existing

        if existing.status == PositionStatus.FILLED and is_position_adjust(inner):
            advice = position_advice_text(inner)
            if advice:
                self._notify_manage(
                    existing,
                    f"AI 建议：{advice}",
                    advisory_only=True,
                )
        return existing

    # ── Tick-based detection ───────────────────────────────────────────────
    def on_tick(
        self,
        symbol: str,
        timeframe: str,
        *,
        high: float,
        low: float,
        bar_ts: int | None = None,
    ) -> Optional[PositionState]:
        """Update the active position against a **closed** bar's high/low.

        Returns the active position after processing (or None if closed/none).
        """
        position = self._store.get_active(symbol, timeframe)
        if position is None:
            return None
        try:
            hi = float(high)
            lo = float(low)
        except (TypeError, ValueError):
            return position

        if position.status == PositionStatus.PLANNED:
            if self._price_touched(position.entry_price, hi, lo):
                position.status = PositionStatus.FILLED
                position.filled_at_ms = _now_ms()
                position.fill_price = position.entry_price
                if bar_ts is not None:
                    position.filled_on_bar_ts = int(bar_ts)
                self._store.upsert_active(position)
                self._notify_entry(position)
            return position

        if position.status == PositionStatus.FILLED:
            if (
                bar_ts is not None
                and position.filled_on_bar_ts is not None
                and int(bar_ts) == int(position.filled_on_bar_ts)
            ):
                return position
            long = position.is_long
            tp = position.take_profit_price
            sl = position.stop_loss_price
            # Check SL first (conservative: assume worst-case intrabar order).
            if sl is not None and self._stop_hit(long, sl, hi, lo):
                self._close(position, exit_price=sl, reason="stop_loss",
                            notify_reason="触及止损")
                return None
            if tp is not None and self._target_hit(long, tp, hi, lo):
                self._close(position, exit_price=tp, reason="take_profit",
                            notify_reason="触及止盈")
                return None
        return position

    # ── Exit helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _resolve_exit_price(
        position: PositionState, current_price: float | None
    ) -> float:
        if current_price is not None:
            return current_price
        if position.fill_price is not None:
            return position.fill_price
        return position.entry_price

    @staticmethod
    def _price_touched(price: float, high: float, low: float) -> bool:
        return low <= price <= high

    @staticmethod
    def _stop_hit(long: bool | None, sl: float, high: float, low: float) -> bool:
        if long is True:
            return low <= sl
        if long is False:
            return high >= sl
        # Unknown direction: any touch counts.
        return low <= sl <= high

    @staticmethod
    def _target_hit(long: bool | None, tp: float, high: float, low: float) -> bool:
        if long is True:
            return high >= tp
        if long is False:
            return low <= tp
        return low <= tp <= high

    def _close(
        self, position: PositionState, *, exit_price: float, reason: str, notify_reason: str
    ) -> None:
        position.exit_price = exit_price
        position.exit_reason = reason
        position.closed_at_ms = _now_ms()
        self._store.close_active(position)
        logger.info("Position closed (%s) %s %s @ %s",
                    reason, position.symbol, position.timeframe, exit_price)
        self._notify_exit(position, notify_reason)

    # ── Notifications ──────────────────────────────────────────────────────
    def _notify_entry(self, position: PositionState) -> None:
        if self._notifier is None:
            return
        from pa_agent.notification import formatter

        self._notifier.notify(
            formatter.format_entry_filled(
                symbol=position.symbol,
                timeframe=position.timeframe,
                direction=position.order_direction,
                entry_price=position.fill_price,
                take_profit_price=position.take_profit_price,
                stop_loss_price=position.stop_loss_price,
            )
        )

    def _notify_exit(self, position: PositionState, reason: str) -> None:
        if self._notifier is None:
            return
        from pa_agent.notification import formatter

        self._notifier.notify(
            formatter.format_exit(
                symbol=position.symbol,
                timeframe=position.timeframe,
                direction=position.order_direction,
                reason=reason,
                exit_price=position.exit_price,
            )
        )

    def _notify_manage(
        self,
        position: PositionState,
        change_text: str,
        *,
        advisory_only: bool = False,
    ) -> None:
        if self._notifier is None:
            return
        from pa_agent.notification import formatter

        self._notifier.notify(
            formatter.format_manage(
                symbol=position.symbol,
                timeframe=position.timeframe,
                direction=position.order_direction,
                change_text=change_text,
                take_profit_price=position.take_profit_price,
                stop_loss_price=position.stop_loss_price,
                advisory_only=advisory_only,
            )
        )
