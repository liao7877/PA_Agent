"""Render analysis decisions into human-readable notification messages.

Pure functions over plain dicts — no PyQt, no HTTP, no record imports — so the
formatting logic stays trivially unit-testable.
"""
from __future__ import annotations

from typing import Any

from pa_agent.ai.api_health import is_api_exception_dict
from pa_agent.notification.decision_card import build_decision_card
from pa_agent.notification.events import NotificationEvent, NotificationMessage

_NO_ORDER_TEXT = "不下单"


def _fmt_price(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _decision_event(order_type: str) -> NotificationEvent:
    """Classify an analysis decision into NEW_ORDER vs NO_TRADE."""
    if order_type and order_type != _NO_ORDER_TEXT:
        return NotificationEvent.NEW_ORDER
    return NotificationEvent.NO_TRADE


def classify_decision(decision: dict) -> NotificationEvent:
    """Public helper: which scene does this stage-2 decision belong to?"""
    inner = decision.get("decision", decision) if isinstance(decision, dict) else {}
    order_type = str(inner.get("order_type") or _NO_ORDER_TEXT)
    return _decision_event(order_type)


def format_decision(
    *,
    symbol: str,
    timeframe: str,
    decision: dict,
    stage1_diagnosis: dict | None = None,
) -> NotificationMessage:
    """Build a card-style message from a stage-2 decision dict.

    *decision* may be the full stage-2 JSON (``{"decision": {...}}``) or the
    inner decision sub-dict. Markdown body mirrors the GUI decision panel.
    """
    root = decision if isinstance(decision, dict) else {}
    inner = root.get("decision", root) if isinstance(root, dict) else {}
    order_type = str(inner.get("order_type") or _NO_ORDER_TEXT)
    event = _decision_event(order_type)

    title, markdown, plain = build_decision_card(
        symbol=symbol,
        timeframe=timeframe,
        decision_root=root,
        stage1_diagnosis=stage1_diagnosis,
    )

    return NotificationMessage(
        event=event,
        title=title,
        text=markdown,
        plain_text=plain,
        fields={
            "symbol": symbol,
            "timeframe": timeframe,
            "order_type": order_type,
            "order_direction": inner.get("order_direction"),
            "entry_price": inner.get("entry_price"),
            "take_profit_price": inner.get("take_profit_price"),
            "stop_loss_price": inner.get("stop_loss_price"),
        },
    )


def is_api_exception(exc: dict | None) -> bool:
    """Public alias used by notification routing."""
    return is_api_exception_dict(exc)


def format_api_error(
    *,
    message: str,
    symbol: str = "",
    timeframe: str = "",
    stage: str = "",
    source: str = "analysis",
    exception: dict | None = None,
) -> NotificationMessage:
    """Build a message for AI API connectivity / upstream failures."""
    pair = f"{symbol} {timeframe}".strip()
    title_scope = f" · {pair}" if pair else ""
    title = f"⚠ API 异常{title_scope}"
    exc = exception if isinstance(exception, dict) else {}
    detail = (message or str(exc.get("message") or "")).strip()
    stage_text = (stage or str(exc.get("stage") or "")).strip()
    source_text = (source or str(exc.get("source") or "analysis")).strip()
    lines = [f"来源: {source_text}"]
    if stage_text:
        lines.append(f"阶段: {stage_text}")
    if detail:
        lines.append(f"信息: {_truncate(detail, 320)}")
    return NotificationMessage(
        event=NotificationEvent.API_ERROR,
        title=title,
        text="\n".join(lines),
        fields={
            "symbol": symbol,
            "timeframe": timeframe,
            "stage": stage_text,
            "source": source_text,
        },
    )


def format_error(*, symbol: str, timeframe: str, exception: dict) -> NotificationMessage:
    """Build a message for a failed/exception analysis."""
    pair = f"{symbol} {timeframe}".strip()
    category = str(exception.get("category") or exception.get("type") or "error")
    message = str(exception.get("message") or "").strip()
    stage = str(exception.get("stage") or "")
    title = f"⚠ 分析异常 · {pair}"
    lines = [f"类别: {category}"]
    if stage:
        lines.append(f"阶段: {stage}")
    if message:
        lines.append(f"信息: {_truncate(message, 240)}")
    return NotificationMessage(
        event=NotificationEvent.ERROR,
        title=title,
        text="\n".join(lines),
        fields={"symbol": symbol, "timeframe": timeframe, "category": category},
    )


def format_entry_filled(
    *, symbol: str, timeframe: str, direction: str, entry_price: Any,
    take_profit_price: Any = None, stop_loss_price: Any = None,
) -> NotificationMessage:
    """Build a message when a planned order is confirmed filled."""
    pair = f"{symbol} {timeframe}".strip()
    title = f"✅ 入场成交 · {pair} · {direction or '—'}"
    lines = [
        f"方向: {direction or '—'}",
        f"成交价: {_fmt_price(entry_price)}",
        f"止盈: {_fmt_price(take_profit_price)}",
        f"止损: {_fmt_price(stop_loss_price)}",
    ]
    return NotificationMessage(
        event=NotificationEvent.ENTRY_FILLED,
        title=title,
        text="\n".join(lines),
        fields={
            "symbol": symbol,
            "timeframe": timeframe,
            "order_direction": direction,
            "entry_price": entry_price,
        },
    )


def format_exit(
    *, symbol: str, timeframe: str, direction: str, reason: str,
    exit_price: Any = None, pnl_text: str = "",
) -> NotificationMessage:
    """Build a message when a position is closed."""
    pair = f"{symbol} {timeframe}".strip()
    title = f"🏁 出场 · {pair} · {direction or '—'}"
    lines = [
        f"方向: {direction or '—'}",
        f"出场原因: {reason}",
        f"出场价: {_fmt_price(exit_price)}",
    ]
    if pnl_text:
        lines.append(f"盈亏: {pnl_text}")
    return NotificationMessage(
        event=NotificationEvent.EXIT,
        title=title,
        text="\n".join(lines),
        fields={"symbol": symbol, "timeframe": timeframe, "reason": reason},
    )


def format_manage(
    *, symbol: str, timeframe: str, direction: str, change_text: str,
    take_profit_price: Any = None, stop_loss_price: Any = None,
    advisory_only: bool = False,
) -> NotificationMessage:
    """Build a message when an open position's TP/SL is adjusted or advised."""
    pair = f"{symbol} {timeframe}".strip()
    title_kind = "持仓建议" if advisory_only else "持仓调整"
    title = f"🔧 {title_kind} · {pair} · {direction or '—'}"
    lines = [
        f"方向: {direction or '—'}",
        f"{'建议' if advisory_only else '调整'}: {change_text}",
        f"当前止盈: {_fmt_price(take_profit_price)}",
        f"当前止损: {_fmt_price(stop_loss_price)}",
    ]
    return NotificationMessage(
        event=NotificationEvent.MANAGE,
        title=title,
        text="\n".join(lines),
        fields={"symbol": symbol, "timeframe": timeframe},
    )


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
