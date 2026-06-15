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
