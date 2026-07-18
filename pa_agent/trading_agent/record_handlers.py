"""Notification dispatch and position tracking hooks for the main window."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def bind_stream_notifier(window: Any) -> None:
    notifier = getattr(window._ctx, "notifier", None)  # noqa: SLF001
    if notifier is not None:
        window._ai_sidebar.bind_notifier(notifier)  # noqa: SLF001


def dispatch_decision_notification(window: Any, record: Any) -> None:
    notifier = getattr(window._ctx, "notifier", None)  # noqa: SLF001
    if notifier is None or getattr(window, "_demo_mode", False):  # noqa: SLF001
        return
    active_position = None
    try:
        meta = getattr(record, "meta", None)
        symbol = getattr(meta, "symbol", "") if meta else ""
        timeframe = getattr(meta, "timeframe", "") if meta else ""
        tracker = getattr(window._ctx, "position_tracker", None)  # noqa: SLF001
        if tracker is not None and symbol and timeframe:
            active_position = tracker.get_active(symbol, timeframe)
    except Exception:  # noqa: BLE001
        active_position = None
    try:
        instrument = None
        manager = getattr(window._ctx, "instrument_manager", None)  # noqa: SLF001
        if manager is not None and symbol and timeframe:
            for runtime in manager.runtimes():
                if runtime.config.symbol == symbol and runtime.config.timeframe == timeframe:
                    instrument = runtime.config
                    break
        notifier.notify_record(record, active_position=active_position, instrument=instrument)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Decision notification dispatch failed: %s", exc)


def notify_api_failure_if_needed(window: Any, exc: BaseException, *, context: str) -> None:
    notifier = getattr(window._ctx, "notifier", None)  # noqa: SLF001
    if notifier is None or not hasattr(notifier, "notify_api_failure"):
        return
    try:
        from pa_agent.ai.api_health import is_api_error

        if not is_api_error(exc):
            return
        source, _, stage = context.partition("/")
        notifier.notify_api_failure(
            message=str(exc),
            source=source or "analysis",
            stage=stage or "worker",
        )
    except Exception as notify_exc:  # noqa: BLE001
        logger.warning("Analysis API failure notification skipped: %s", notify_exc)


def update_position_from_record(window: Any, record: Any) -> None:
    tracker = getattr(window._ctx, "position_tracker", None)  # noqa: SLF001
    if tracker is None or getattr(window, "_demo_mode", False):  # noqa: SLF001
        return
    try:
        meta = getattr(record, "meta", None)
        symbol = getattr(meta, "symbol", "") if meta else ""
        timeframe = getattr(meta, "timeframe", "") if meta else ""
        if not symbol or not timeframe:
            return
        decision = getattr(record, "stage2_decision", None)
        exc_info = getattr(record, "exception", None)
        from pa_agent.positions.decision_fields import (
            should_apply_position_despite_validation,
        )

        apply_position = decision and (
            not exc_info
            or exc_info.get("position_apply_allowed")
            or should_apply_position_despite_validation(
                exc_info, stage2_decision=decision
            )
        )
        if apply_position:
            record_id = getattr(meta, "timestamp_local_iso", None)
            current_price = None
            fill_bar_ts = None
            first_tracked_bar_ts = None
            kline_data = getattr(record, "kline_data", None) or []
            if kline_data:
                head = kline_data[0]
                try:
                    current_price = float(head.get("close"))
                except (TypeError, ValueError, AttributeError):
                    current_price = None
                try:
                    from pa_agent.data.datetime_ts import ts_open_to_ms

                    fill_bar_ts = int(ts_open_to_ms(head.get("ts_open")))
                except (TypeError, ValueError):
                    fill_bar_ts = None
            latest_bars = list(getattr(window, "_last_frame_ready_bars", None) or [])
            if latest_bars:
                latest = latest_bars[0]
                try:
                    current_price = float(getattr(latest, "close", None))
                except (TypeError, ValueError):
                    try:
                        current_price = float(latest.get("close"))
                    except (TypeError, ValueError, AttributeError):
                        pass
                hlt = _bar_high_low_ts(latest)
                if hlt is not None:
                    _, _, first_tracked_bar_ts = hlt
            if exc_info:
                from pa_agent.ai.stage2_normalizer import normalize_stage2

                stage1_diag = getattr(record, "stage1_diagnosis", None)
                decision = normalize_stage2(
                    decision,
                    normalization_mode="lenient",
                    decision_stance=getattr(meta, "decision_stance", None),
                    stage1_json=stage1_diag if isinstance(stage1_diag, dict) else None,
                )
            tracker.apply_decision(
                symbol=symbol,
                timeframe=timeframe,
                decision=decision,
                record_id=record_id,
                current_price=current_price,
                fill_bar_ts=fill_bar_ts,
                first_tracked_bar_ts=first_tracked_bar_ts,
            )
        sync_chart_active_position(window, symbol, timeframe)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Position update from record failed: %s", exc)


def sync_chart_active_position(window: Any, symbol: str, timeframe: str) -> None:
    tracker = getattr(window._ctx, "position_tracker", None)  # noqa: SLF001
    chart = getattr(window, "_chart_widget", None)  # noqa: SLF001
    if tracker is None or chart is None:
        return
    position = tracker.get_active(symbol, timeframe)
    if position is None:
        chart.set_active_position(None)
    else:
        chart.set_active_position(position.model_dump(mode="json"))


def _bar_high_low_ts(bar: object) -> tuple[float, float, int | None] | None:
    """Extract high/low and open ts from a KlineBar or snapshot dict."""
    high = getattr(bar, "high", None)
    low = getattr(bar, "low", None)
    if high is None and isinstance(bar, dict):
        high = bar.get("high")
        low = bar.get("low")
    if high is None or low is None:
        return None
    try:
        from pa_agent.data.datetime_ts import ts_open_to_ms

        ts_open = getattr(bar, "ts_open", None)
        if ts_open is None and isinstance(bar, dict):
            ts_open = bar.get("ts_open")
        return float(high), float(low), int(ts_open_to_ms(ts_open))
    except (TypeError, ValueError):
        return None


def check_position_on_tick(
    window: Any,
    bars: Any,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    sync_chart: bool = True,
) -> None:
    """Track active positions on each live data refresh from a runtime feed."""
    tracker = getattr(window._ctx, "position_tracker", None)  # noqa: SLF001
    if tracker is None or getattr(window, "_demo_mode", False) or not bars:  # noqa: SLF001
        return
    symbol = symbol or window._symbol_combo.currentText().strip()  # noqa: SLF001
    timeframe = timeframe or window._tf_combo.currentText()  # noqa: SLF001
    position = tracker.get_active(symbol, timeframe)
    if position is None:
        return

    bars_list = list(bars)

    # Forward-track with the newest bar (K0 when forming) on every live data refresh.
    tick_bar = bars_list[0]
    if tick_bar is None:
        return
    hlt = _bar_high_low_ts(tick_bar)
    if hlt is None:
        return
    high, low, bar_ts = hlt
    current_price = getattr(tick_bar, "close", None)
    if current_price is None and isinstance(tick_bar, dict):
        current_price = tick_bar.get("close")
    try:
        tracker.on_live_price(
            symbol,
            timeframe,
            high=high,
            low=low,
            current_price=current_price,
            bar_ts=bar_ts,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Position tick check failed: %s", exc)
    if sync_chart:
        sync_chart_active_position(window, symbol, timeframe)


def has_active_position(window: Any, symbol: str, timeframe: str) -> bool:
    if getattr(window, "_demo_mode", False):  # noqa: SLF001
        return False
    tracker = getattr(window._ctx, "position_tracker", None)  # noqa: SLF001
    if tracker is None:
        return False
    try:
        return tracker.get_active(symbol, timeframe) is not None
    except Exception:  # noqa: BLE001
        return False


def keep_analysis_tracking_allowed(window: Any, symbol: str, timeframe: str) -> bool:
    from pa_agent.config.tracking_schedule import keep_analysis_tracking_allowed

    settings = getattr(window._ctx, "settings", None)  # noqa: SLF001
    return keep_analysis_tracking_allowed(
        settings,
        has_active_position=has_active_position(window, symbol, timeframe),
    )
