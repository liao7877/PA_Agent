from __future__ import annotations

import threading
import time

from pa_agent.config.settings import InstrumentSettings, Settings
from pa_agent.data.base import DataSourceTransientError
from pa_agent.data.refresh_loop import RefreshLoop
from pa_agent.instruments import InstrumentRuntimeManager
from pa_agent.util.threading import CancelToken


class _AlwaysFailingSource:
    def __init__(self) -> None:
        self.called = threading.Event()

    def latest_snapshot(self, _count: int):
        self.called.set()
        raise DataSourceTransientError("temporary")


def test_refresh_loop_cancel_interrupts_long_backoff() -> None:
    source = _AlwaysFailingSource()
    token = CancelToken()
    loop = RefreshLoop(source, n_bars=10, interval_ms=1000, cancel_token=token)
    loop._BACKOFF_BASE_S = 10.0
    loop._MAX_BACKOFF_S = 10.0

    loop.start()
    assert source.called.wait(timeout=1.0)
    time.sleep(0.05)  # allow the worker to enter its ten-second backoff wait

    started = time.monotonic()
    token.set()
    assert loop.wait(1000)
    assert time.monotonic() - started < 0.8


def test_reload_keeps_runtime_when_refresh_thread_has_not_stopped(monkeypatch) -> None:
    settings = Settings()
    settings.instruments.items = [
        InstrumentSettings(id="gold", symbol="XAUUSDm", timeframe="15m")
    ]
    manager = InstrumentRuntimeManager(settings=settings)
    runtime = manager.get("gold")
    assert runtime is not None

    settings.instruments.items = []
    monkeypatch.setattr(manager, "stop_runtime", lambda _key, wait_ms=5000: False)

    manager.reload_from_settings()

    assert manager.get("gold") is runtime
