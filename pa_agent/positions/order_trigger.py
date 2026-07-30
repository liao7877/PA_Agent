"""Shared, gap-aware pending-order trigger semantics."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderTriggerResult:
    triggered: bool
    armed: bool
    gap_through: bool = False
    fill_price: float | None = None
    reason: str = ""


def trigger_is_armed(
    *,
    order_type: str,
    is_long: bool | None,
    entry: float,
    current_price: float | None,
) -> bool:
    if current_price is None or is_long is None:
        return False
    if order_type == "限价单":
        return current_price >= entry if is_long else current_price <= entry
    if order_type == "突破单":
        return current_price <= entry if is_long else current_price >= entry
    return order_type == "市价单"


def evaluate_order_trigger(
    *,
    order_type: str,
    is_long: bool | None,
    entry: float,
    bar_open: float | None,
    bar_high: float,
    bar_low: float,
    bar_close: float | None,
    armed: bool,
    previous_price: float | None,
) -> OrderTriggerResult:
    """Evaluate a post-placement OHLC observation without inventing chronology."""
    if is_long is None or order_type not in ("限价单", "突破单"):
        return OrderTriggerResult(False, armed, reason="订单方向或类型无效")
    if not armed:
        newly_armed = trigger_is_armed(
            order_type=order_type,
            is_long=is_long,
            entry=entry,
            current_price=previous_price,
        )
        if not newly_armed:
            return OrderTriggerResult(False, False, reason="缺少计划后的arming证据")
        armed = True

    open_ = float(bar_open) if bar_open is not None else None
    high = float(bar_high)
    low = float(bar_low)
    if open_ is not None and not (low <= open_ <= high):
        # Reject malformed/synthetic OHLC instead of inventing a gap from an open
        # that is outside its own bar range.
        open_ = None
    range_covers_entry = low <= entry <= high

    if order_type == "限价单":
        if is_long:
            if open_ is not None and open_ < entry and high < entry and previous_price is not None and previous_price >= entry:
                return OrderTriggerResult(True, True, True, open_, "buy limit跳空获得价格改善")
            triggered = range_covers_entry
        else:
            if open_ is not None and open_ > entry and low > entry and previous_price is not None and previous_price <= entry:
                return OrderTriggerResult(True, True, True, open_, "sell limit跳空获得价格改善")
            triggered = range_covers_entry
    else:
        if is_long:
            if open_ is not None and open_ > entry and low > entry and previous_price is not None and previous_price <= entry:
                return OrderTriggerResult(True, True, True, open_, "buy stop跳空按开盘价触发")
            triggered = range_covers_entry
        else:
            if open_ is not None and open_ < entry and high < entry and previous_price is not None and previous_price >= entry:
                return OrderTriggerResult(True, True, True, open_, "sell stop跳空按开盘价触发")
            triggered = range_covers_entry

    if triggered:
        return OrderTriggerResult(True, True, False, entry, "价格在计划后触及/穿越入场价")
    return OrderTriggerResult(False, True, reason="尚未触发")
