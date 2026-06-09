"""Structured position-management fields on stage-2 ``decision``."""
from __future__ import annotations

from typing import Any

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


def has_position_management_intent(inner: dict) -> bool:
    return get_position_action(inner) is not None


def position_advice_text(inner: dict, *, max_len: int = 480) -> str:
    """Human-readable advisory body for notifications (display only)."""
    advice = str(inner.get("position_advice") or "").strip()
    if not advice:
        advice = str(inner.get("reasoning") or "").strip()
    advice = " ".join(advice.split())
    if len(advice) <= max_len:
        return advice
    return advice[: max_len - 1] + "…"
