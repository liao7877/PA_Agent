"""1 Hz data refresh loop running on a dedicated QThread."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from pa_agent.data.base import DataSource, DataSourceTransientError, KlineBar
from pa_agent.data.snapshot import INDICATOR_WARMUP_BARS

if TYPE_CHECKING:
    from pa_agent.util.threading import CancelToken

logger = logging.getLogger(__name__)

from PyQt6.QtCore import QThread, pyqtSignal, QObject


class RefreshLoop(QThread):
    """Fetches the latest K-line snapshot every *interval_ms* milliseconds.

    Signals
    -------
    frame_ready(list[KlineBar])
        Emitted after each successful fetch with the raw bar list (newest-first).
    status_changed(str)
        Emitted with a human-readable status string (e.g. "数据延迟").
    """

    frame_ready = pyqtSignal(list)
    status_changed = pyqtSignal(str)

    # Backoff constants
    _MAX_BACKOFF_S = 10.0       # cap exponential backoff at 10 seconds
    _BACKOFF_BASE_S = 0.5      # initial backoff = 0.5s, doubles each failure

    def __init__(
        self,
        data_source: DataSource,
        n_bars: int,
        interval_ms: int = 1000,
        cancel_token: "CancelToken | None" = None,
        parent: "QObject | None" = None,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = data_source
        self._n_bars = n_bars
        self._interval_ms = interval_ms
        self._cancel_token = cancel_token
        self._symbol = (symbol or "").strip()
        self._timeframe = (timeframe or "").strip()
        self._connected = bool(getattr(data_source, "_connected", False))
        self._subscribed = False
        self._consecutive_failures = 0
        self._failure_threshold_s = 5.0
        self._in_flight = False  # guard against overlapping fetches

    def _wait_or_cancel(self, timeout_s: float) -> bool:
        """Wait up to *timeout_s* and return True when cancellation wins."""
        token = self._cancel_token
        if token is None:
            time.sleep(timeout_s)
            return False
        return token.wait(timeout_s)

    def _record_failure(
        self,
        exc: BaseException,
        failure_start: float | None,
        *,
        unexpected: bool,
    ) -> float:
        self._connected = bool(getattr(self._source, "_connected", False))
        if not self._connected:
            self._subscribed = False
        self._consecutive_failures += 1
        if failure_start is None:
            failure_start = time.monotonic()
        user_msg = str(exc).strip()
        if user_msg:
            self.status_changed.emit(
                f"数据刷新异常：{user_msg}" if unexpected else user_msg
            )
        elif time.monotonic() - failure_start >= self._failure_threshold_s:
            self.status_changed.emit("数据刷新异常" if unexpected else "数据延迟")
        return failure_start

    def run(self) -> None:  # noqa: C901
        """Main loop — runs on the worker thread."""
        failure_start: float | None = None

        while True:
            if self._cancel_token is not None and self._cancel_token.is_set():
                logger.debug("RefreshLoop cancelled")
                break

            # Skip this tick if a previous fetch is still in flight.
            # This prevents overlapping WebSocket connections that trigger
            # TradingView rate-limiting (especially in nologin mode).
            if self._in_flight:
                if self._wait_or_cancel(0.5):
                    break
                continue

            t0 = time.monotonic()
            self._in_flight = True
            try:
                try:
                    if not self._connected:
                        connect = getattr(self._source, "connect", None)
                        if callable(connect):
                            self.status_changed.emit("连接中")
                            connect()
                        self._connected = True
                        self._subscribed = False
                    if self._symbol and self._timeframe and not self._subscribed:
                        subscribe = getattr(self._source, "subscribe", None)
                        if callable(subscribe):
                            subscribe(self._symbol, self._timeframe)
                        self._subscribed = True
                        self.status_changed.emit("行情已连接")
                    bars = self._source.latest_snapshot(
                        self._n_bars + INDICATOR_WARMUP_BARS + 5
                    )
                    if self._consecutive_failures > 0:
                        # Clear any previous error message from the status bar.
                        self.status_changed.emit("")
                    self._consecutive_failures = 0
                    failure_start = None
                    if bars:
                        self.frame_ready.emit(bars)

                except DataSourceTransientError as exc:
                    logger.debug("RefreshLoop transient error: %s", exc)
                    failure_start = self._record_failure(
                        exc, failure_start, unexpected=False
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error("RefreshLoop unexpected error: %s", exc, exc_info=True)
                    failure_start = self._record_failure(
                        exc, failure_start, unexpected=True
                    )
            finally:
                self._in_flight = False

            # Exponential backoff on repeated failures to avoid hammering
            # TradingView's WebSocket endpoint
            if self._consecutive_failures > 0:
                backoff_s = min(
                    self._BACKOFF_BASE_S * (2 ** (self._consecutive_failures - 1)),
                    self._MAX_BACKOFF_S,
                )
                logger.debug(
                    "RefreshLoop backoff %.1fs after %d consecutive failure(s)",
                    backoff_s,
                    self._consecutive_failures,
                )
                if self._wait_or_cancel(backoff_s):
                    logger.debug("RefreshLoop cancelled during backoff")
                    break
                continue

            elapsed_ms = (time.monotonic() - t0) * 1000
            sleep_ms = max(0.0, self._interval_ms - elapsed_ms)
            if sleep_ms > 0 and self._wait_or_cancel(sleep_ms / 1000.0):
                logger.debug("RefreshLoop cancelled during interval wait")
                break

