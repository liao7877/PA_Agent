"""Structured position-management fields on stage-2 ``decision``."""
from __future__ import annotations

from typing import Any

_TRADE_ORDER_TYPES = frozenset({"限价单", "突破单", "市价单"})
_NO_ORDER_TEXT = "不下单"

# Validator prefixes that reject the trade thesis — not mere JSON/format issues.
_SUBSTANTIVE_INVALID_PREFIXES = (
    "metrics:",
    "trace_semantic:",
    "trace:",
    "s2:",
)

# AI 在「已有持仓」场景下必须填写的显式意图（枚举，不靠正文关键词猜测）。
POSITION_ACTION_HOLD = "持有"
POSITION_ACTION_ADJUST = "调整"
POSITION_ACTION_CLOSE = "平仓"

_VALID_POSITION_ACTIONS = frozenset({
    POSITION_ACTION_HOLD,
    POSITION_ACTION_ADJUST,
    POSITION_ACTION_CLOSE,
})


def normalize_position_action(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text in _VALID_POSITION_ACTIONS else None


def get_position_action(inner: dict) -> str | None:
    if not isinstance(inner, dict):
        return None
    return normalize_position_action(inner.get("position_action"))


def is_position_close(inner: dict) -> bool:
    return get_position_action(inner) == POSITION_ACTION_CLOSE


def is_position_adjust(inner: dict) -> bool:
    return get_position_action(inner) == POSITION_ACTION_ADJUST


def is_position_hold(inner: dict) -> bool:
    return get_position_action(inner) == POSITION_ACTION_HOLD


def is_planned_order_cancel(inner: dict) -> bool:
    """True when AI intends to drop a pending (not yet filled) planned order.

    Matches prompt contract:
    - ``order_type=不下单`` and ``position_action`` is null / omitted → 撤单
    - ``position_action=平仓`` on a plan → treat as撤单（尚未成交，无仓可平）
    Does **not** match ``position_action=持有`` or ``调整`` (the latter may update TP/SL).
    """
    if str(inner.get("order_type") or _NO_ORDER_TEXT).strip() != _NO_ORDER_TEXT:
        return False
    action = get_position_action(inner)
    if action == POSITION_ACTION_HOLD:
        return False
    if action == POSITION_ACTION_ADJUST:
        return False
    return True


def has_position_management_intent(inner: dict) -> bool:
    return get_position_action(inner) is not None


def decision_inner(decision_root: dict | None) -> dict | None:
    if not isinstance(decision_root, dict):
        return None
    inner = decision_root.get("decision", decision_root)
    return inner if isinstance(inner, dict) else None


def is_actionable_trade_decision(decision_root: dict | None) -> bool:
    """True when stage-2 JSON states a concrete new entry (not 不下单 / 持仓管理-only)."""
    inner = decision_inner(decision_root)
    if inner is None:
        return False
    order_type = str(inner.get("order_type") or "").strip()
    if order_type not in _TRADE_ORDER_TYPES:
        return False
    if inner.get("entry_price") is None:
        return False
    if not str(inner.get("order_direction") or "").strip():
        return False
    return True


def has_substantive_validation_failure(exc_info: dict | None) -> bool:
    """True when validation failed for trade logic, not just schema/format."""
    if not isinstance(exc_info, dict):
        return False
    invalid = [str(x) for x in (exc_info.get("invalid_fields") or [])]
    return any(
        field.startswith(_SUBSTANTIVE_INVALID_PREFIXES) for field in invalid
    )


def is_format_only_validation_error(exc_info: dict | None) -> bool:
    """True when the failure is schema/format/category-c style, not broken JSON or plain text."""
    if not isinstance(exc_info, dict):
        return False
    if exc_info.get("type") != "validation_error":
        return False
    category = str(exc_info.get("category") or "").strip().lower()
    if category in ("d",):
        return False
    if has_substantive_validation_failure(exc_info):
        return False
    return True


def should_apply_position_despite_validation(
    exc_info: dict | None,
    *,
    stage2_decision: dict | None,
) -> bool:
    """Apply software position tracking when AI decision is clear and only format checks failed."""
    if not is_actionable_trade_decision(stage2_decision):
        return False
    if not exc_info:
        return True
    if exc_info.get("type") != "validation_error":
        return False
    if str(exc_info.get("stage") or "") != "stage2":
        return False
    if has_substantive_validation_failure(exc_info):
        return False
    category = str(exc_info.get("category") or "").strip().lower()
    if category == "a":
        return bool(exc_info.get("decision_preserved"))
    if category in ("b", "c"):
        return True
    return bool(exc_info.get("decision_preserved"))


def position_advice_text(inner: dict, *, max_len: int = 480) -> str:
    """Human-readable advisory body for notifications (display only)."""
    advice = str(inner.get("position_advice") or "").strip()
    if not advice:
        advice = str(inner.get("reasoning") or "").strip()
    advice = " ".join(advice.split())
    if len(advice) <= max_len:
        return advice
    return advice[: max_len - 1] + "…"


def _price_equal(a: Any, b: Any) -> bool:
    try:
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def planned_order_matches_decision(position: Any, inner: dict) -> bool:
    """True when a planned-order decision keeps the same type, direction, and three prices."""
    order_type = str(inner.get("order_type") or "").strip()
    if order_type not in _TRADE_ORDER_TYPES:
        return False
    if order_type != str(position.order_type or "").strip():
        return False
    if str(inner.get("order_direction") or "").strip() != str(position.order_direction or "").strip():
        return False
    return (
        _price_equal(inner.get("entry_price"), position.entry_price)
        and _price_equal(inner.get("take_profit_price"), position.take_profit_price)
        and _price_equal(inner.get("stop_loss_price"), position.stop_loss_price)
    )


def should_notify_analysis_decision(
    decision_root: dict | None,
    active_position: Any | None,
    *,
    record_id: str | None = None,
) -> bool:
    """Whether to send the full analysis decision card to DingTalk.

    Only brand-new entries (or fresh watch/no-trade with no active position) notify.
    Ongoing hold / maintain-pending / modify / cancel are handled by the position tracker.
    """
    if active_position is None:
        return True
    if not record_id or not active_position.opened_at_record_id:
        return False
    if str(record_id) != str(active_position.opened_at_record_id):
        return False
    inner = decision_inner(decision_root)
    if inner is None:
        return False
    order_type = str(inner.get("order_type") or _NO_ORDER_TEXT)
    if order_type in _TRADE_ORDER_TYPES and is_actionable_trade_decision(decision_root):
        return True
    return order_type == "市价单" and str(active_position.order_type or "") == "市价单"
