"""Per-instrument runtime helpers for background watchlist monitoring."""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from pa_agent.config.settings import (
    AIProviderSettings,
    FeishuSettings,
    InstrumentSettings,
    NotificationSettings,
    PushPlusSettings,
    Settings,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EffectiveInstrumentSettings:
    provider: AIProviderSettings
    notification: NotificationSettings
    feishu: FeishuSettings
    pushplus: PushPlusSettings


@dataclass(slots=True)
class InstrumentRuntime:
    config: InstrumentSettings
    data_source: Any = None
    refresh_loop: Any = None
    refresh_cancel_token: Any = None
    last_bars: list[Any] | None = None
    last_error: str = ""
    status: str = "未启动"
    analysis_in_progress: bool = False
    pending_analysis: bool = False
    analysis_requested: bool = False
    last_analysis_record: Any = None
    last_analysis_frame: Any = None
    analysis_previous_record: Any = None
    keep_last_closed_ts: int | None = None
    keep_submit_closed_ts: int | None = None
    keep_outside_window: bool = False
    current_price: float | None = None
    last_analysis_text: str = "—"
    background_prep: Any = None
    background_worker: Any = None

    @property
    def key(self) -> str:
        return instrument_key(self.config)

    @property
    def label(self) -> str:
        name = (self.config.name or "").strip()
        pair = f"{self.config.symbol} {self.config.timeframe}".strip()
        return f"{name} · {pair}" if name and name != self.config.symbol else pair


class InstrumentRuntimeManager(QObject):
    runtime_changed = pyqtSignal(str)
    status_changed = pyqtSignal(str, str)
    bars_ready = pyqtSignal(str, list)

    def __init__(self, *, settings: Settings, logger_: logging.Logger | None = None) -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger_ or logger
        self._runtimes: dict[str, InstrumentRuntime] = {}
        self.reload_from_settings()

    @property
    def settings(self) -> Settings:
        return self._settings

    def reload_from_settings(self) -> None:
        seen: set[str] = set()
        for cfg in self._settings.instruments.items:
            key = instrument_key(cfg)
            seen.add(key)
            runtime = self._runtimes.get(key)
            if runtime is None:
                self._runtimes[key] = InstrumentRuntime(config=cfg)
            else:
                runtime.config = cfg
        for key in list(self._runtimes):
            if key not in seen:
                self.stop_runtime(key)
                self._runtimes.pop(key, None)

    def runtimes(self) -> list[InstrumentRuntime]:
        order = [instrument_key(cfg) for cfg in self._settings.instruments.items]
        return [self._runtimes[key] for key in order if key in self._runtimes]

    def get(self, key: str) -> InstrumentRuntime | None:
        return self._runtimes.get(key)

    def first_enabled_key(self) -> str:
        for runtime in self.runtimes():
            if runtime.config.enabled:
                return runtime.key
        runtimes = self.runtimes()
        return runtimes[0].key if runtimes else ""

    def effective_settings(self, config_or_key: InstrumentSettings | str) -> EffectiveInstrumentSettings:
        cfg = self._coerce_config(config_or_key)
        return EffectiveInstrumentSettings(
            provider=copy.deepcopy(cfg.provider if cfg.provider_override_enabled else self._settings.provider),
            notification=copy.deepcopy(
                cfg.notification if cfg.notification_override_enabled else self._settings.notification
            ),
            feishu=copy.deepcopy(cfg.feishu if cfg.feishu_override_enabled else self._settings.feishu),
            pushplus=copy.deepcopy(
                cfg.pushplus if cfg.pushplus_override_enabled else self._settings.pushplus
            ),
        )

    def ensure_data_source(self, key: str) -> Any:
        runtime = self._runtimes[key]
        if runtime.data_source is not None and getattr(runtime.data_source, "_connected", False):
            return runtime.data_source
        from pa_agent.data.factory import create_data_source
        from pa_agent.data.tradingview import TradingViewSource

        mt5_path = getattr(self._settings.general, "mt5_terminal_path", "") or ""
        source = create_data_source(runtime.config.data_source, mt5_terminal_path=mt5_path)
        if isinstance(source, TradingViewSource):
            source.set_exchange(runtime.config.tradingview_exchange or "")
        source.connect()
        source.subscribe(runtime.config.symbol, runtime.config.timeframe)
        runtime.data_source = source
        runtime.status = "行情已连接"
        runtime.last_error = ""
        self.status_changed.emit(key, runtime.status)
        self.runtime_changed.emit(key)
        return source

    def start_runtime(
        self,
        key: str,
        *,
        n_bars: int,
        interval_ms: int,
        frame_handler: Callable[[str, list], None] | None = None,
        status_handler: Callable[[str, str], None] | None = None,
    ) -> None:
        runtime = self._runtimes[key]
        loop = runtime.refresh_loop
        if loop is not None and ((hasattr(loop, "isRunning") and loop.isRunning()) or (hasattr(loop, "isActive") and loop.isActive())):
            return
        source = self.ensure_data_source(key)
        from pa_agent.data.mt5 import MT5Source
        from pa_agent.data.refresh_loop import RefreshLoop
        from pa_agent.util.threading import CancelToken

        if runtime.config.data_source in ("akshare", "eastmoney", "tushare") and interval_ms < 2500:
            interval_ms = 2500

        def _on_bars(bars: list) -> None:
            runtime.last_bars = list(bars)
            runtime.last_error = ""
            runtime.status = "运行中"
            runtime.current_price = _latest_close(bars)
            self.bars_ready.emit(key, list(bars))
            self.runtime_changed.emit(key)
            if frame_handler is not None:
                frame_handler(key, list(bars))

        def _on_status(text: str) -> None:
            runtime.last_error = text or ""
            runtime.status = text or "运行中"
            self.status_changed.emit(key, runtime.status)
            self.runtime_changed.emit(key)
            if status_handler is not None:
                status_handler(key, text)

        if isinstance(source, MT5Source):
            timer = QTimer(self)
            timer.setInterval(interval_ms)

            def _poll_mt5() -> None:
                try:
                    bars = source.latest_snapshot(n_bars + 5)
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("MT5 refresh failed (%s): %s", key, exc)
                    _on_status(str(exc))
                    return
                if bars:
                    _on_bars(bars)

            timer.timeout.connect(_poll_mt5)
            runtime.refresh_loop = timer
            runtime.refresh_cancel_token = None
            _poll_mt5()
            timer.start()
        else:
            token = CancelToken()
            loop = RefreshLoop(
                data_source=source,
                n_bars=n_bars,
                interval_ms=interval_ms,
                cancel_token=token,
            )
            runtime.refresh_cancel_token = token
            runtime.refresh_loop = loop
            loop.frame_ready.connect(_on_bars)
            loop.status_changed.connect(_on_status)
            loop.start()

        runtime.status = "运行中"
        self.runtime_changed.emit(key)

    def stop_runtime(self, key: str, *, wait_ms: int = 5000) -> bool:
        runtime = self._runtimes.get(key)
        if runtime is None:
            return True
        loop = runtime.refresh_loop
        token = runtime.refresh_cancel_token
        if isinstance(loop, QTimer):
            loop.stop()
            loop.deleteLater()
        else:
            if token is not None:
                token.set()
            if runtime.data_source is not None:
                close_ws = getattr(runtime.data_source, "_close_tv_socket", None)
                if callable(close_ws):
                    try:
                        close_ws()
                    except Exception:  # noqa: BLE001
                        pass
            if loop is not None:
                try:
                    loop.frame_ready.disconnect()
                    loop.status_changed.disconnect()
                except (TypeError, RuntimeError):
                    pass
                if loop.isRunning():
                    loop.wait(wait_ms)
                if loop.isRunning():
                    self._logger.warning("refresh loop still running; retaining runtime %s", key)
                    return False
                loop.deleteLater()
        runtime.refresh_loop = None
        runtime.refresh_cancel_token = None
        runtime.status = "已停止"
        self.runtime_changed.emit(key)
        return True

    def stop_all(self, *, wait_ms: int = 5000) -> bool:
        return all(self.stop_runtime(key, wait_ms=wait_ms) for key in list(self._runtimes))

    def disconnect_all_sources(self) -> None:
        for runtime in self._runtimes.values():
            loop = runtime.refresh_loop
            if loop is not None and hasattr(loop, "isRunning") and loop.isRunning():
                self._logger.warning("source still has active refresh loop; deferring disconnect for %s", runtime.key)
                continue
            source = runtime.data_source
            if source is None:
                continue
            try:
                source.unsubscribe()
            except Exception:  # noqa: BLE001
                pass
            try:
                source.disconnect()
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("instrument source disconnect failed: %s", exc)
            runtime.data_source = None

    def _coerce_config(self, config_or_key: InstrumentSettings | str) -> InstrumentSettings:
        if isinstance(config_or_key, InstrumentSettings):
            return config_or_key
        runtime = self._runtimes.get(config_or_key)
        if runtime is None:
            raise KeyError(config_or_key)
        return runtime.config


def instrument_key(config: InstrumentSettings) -> str:
    raw = (config.id or "").strip()
    if raw:
        return raw
    base = f"{config.data_source}-{config.symbol}-{config.timeframe}"
    return "".join(ch if ch.isalnum() else "-" for ch in base.lower()).strip("-")


def _latest_close(bars: list[Any]) -> float | None:
    if not bars:
        return None
    bar = bars[0]
    value = getattr(bar, "close", None)
    if value is None and isinstance(bar, dict):
        value = bar.get("close")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
