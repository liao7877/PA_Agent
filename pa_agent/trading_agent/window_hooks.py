"""One-call wiring for Trading Agent extensions on MainWindow."""

from __future__ import annotations

from typing import Any

from pa_agent.trading_agent import WINDOW_TITLE
from pa_agent.trading_agent.chart_live import ChartLiveController
from pa_agent.trading_agent.licensing_ui import wire_licensing
from pa_agent.trading_agent.record_handlers import bind_stream_notifier


def wire_main_window(window: Any, license_validator: Any = None) -> None:
    """Apply Trading Agent title, licensing, notifier, and chart-live controller."""
    window.setWindowTitle(WINDOW_TITLE)
    window._chart_live = ChartLiveController(window)  # noqa: SLF001
    wire_licensing(window, license_validator)

def wire_after_sidebar(window: Any) -> None:
    """Call after AISidebar is constructed."""
    bind_stream_notifier(window)
    _sync_chart_position_on_startup(window)


def _sync_chart_position_on_startup(window: Any) -> None:
    """Restore entry/TP/SL overlay lines when an active position exists on launch."""
    from pa_agent.trading_agent.record_handlers import sync_chart_active_position

    symbol_combo = getattr(window, "_symbol_combo", None)
    tf_combo = getattr(window, "_tf_combo", None)
    if symbol_combo is None or tf_combo is None:
        return
    symbol = symbol_combo.currentText().strip()
    timeframe = tf_combo.currentText().strip()
    if not symbol or not timeframe:
        return
    try:
        sync_chart_active_position(window, symbol, timeframe)
    except Exception:  # noqa: BLE001
        pass
