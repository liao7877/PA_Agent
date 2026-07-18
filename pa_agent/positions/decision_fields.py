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
    "signal_chain:",
    "breakout_price:",
    "bar_analysis",
    "decision.entry_basis",
    "decision.order_direction",
)

# AI 在「已有持仓/计划单」场景下必须填写的显式意图（枚举，不靠正文关键词猜测）。
POSITION_ACTION_HOLD = "持有"
POSITION_ACTION_ADJUST = "调整"
POSITION_ACTION_CLOSE = "平仓"
POSITION_ACTION_CANCEL = "撤销"

_VALID_POSITION_ACTIONS = frozenset({
    POSITION_ACTION_HOLD,
    POSITION_ACTION_ADJUST,
    POSITION_ACTION_CLOSE,
    POSITION_ACTION_CANCEL,
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


def is_position_cancel(inner: dict) -> bool:
    return get_position_action(inner) == POSITION_ACTION_CANCEL


def is_position_adjust(inner: dict) -> bool:
    return get_position_action(inner) == POSITION_ACTION_ADJUST


def is_position_hold(inner: dict) -> bool:
    return get_position_action(inner) == POSITION_ACTION_HOLD


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
