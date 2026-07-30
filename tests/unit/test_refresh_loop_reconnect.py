from __future__ import annotations

import threading
import time

from PyQt6.QtCore import Qt

from pa_agent.data.base import DataSourceTransientError
from pa_agent.data.refresh_loop import RefreshLoop
from pa_agent.util.threading import CancelToken


class _EventuallyReadySource:
    def __init__(self) -> None:
        self.connected = False
        self.subscribed = False
        self.connect_calls = 0
        self.fetch_calls = 0
        self.ready = threading.Event()

    def connect(self) -> None:
        self.connect_calls += 1
        if self.connect_calls < 2:
            raise DataSourceTransientError("MT5 initialize() failed: (-6, 'Authorization failed')")
        self.connected = True

    def subscribe(self, _symbol: str, _timeframe: str) -> None:
        assert self.connected
        self.subscribed = True

    def latest_snapshot(self, _count: int):
        assert self.subscribed
        self.fetch_calls += 1
        self.ready.set()
        return [object()]

    def disconnect(self) -> None:
        self.connected = False


class _BlockingConnectSource:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.connect_thread_id: int | None = None

    def connect(self) -> None:
        self.connect_thread_id = threading.get_ident()
        self.release.wait(timeout=1.0)

    def subscribe(self, _symbol: str, _timeframe: str) -> None:
        pass

    def latest_snapshot(self, _count: int):
        return []

    def disconnect(self) -> None:
        self.release.set()


class _UnexpectedThenReadySource:
    def __init__(self) -> None:
        self._connected = True
        self.fetch_calls = 0
        self.ready = threading.Event()

    def latest_snapshot(self, _count: int):
        self.fetch_calls += 1
        if self.fetch_calls == 1:
            raise RuntimeError("unexpected fetch failure")
        self.ready.set()
        return [object()]



def test_refresh_loop_retries_connection_and_recovers_without_restart() -> None:
    source = _EventuallyReadySource()
    token = CancelToken()
    loop = RefreshLoop(
        source,
        n_bars=10,
        interval_ms=50,
        cancel_token=token,
        symbol="XAUUSD",
        timeframe="15m",
    )
    loop._BACKOFF_BASE_S = 0.01
    loop._MAX_BACKOFF_S = 0.01

    loop.start()
    assert source.ready.wait(timeout=1.0)
    token.set()
    assert loop.wait(1000)

    assert source.connect_calls == 2
    assert source.fetch_calls >= 1


def test_refresh_loop_connect_does_not_run_on_calling_thread() -> None:
    source = _BlockingConnectSource()
    token = CancelToken()
    loop = RefreshLoop(
        source,
        n_bars=10,
        interval_ms=50,
        cancel_token=token,
        symbol="XAUUSD",
        timeframe="15m",
    )
    caller_thread_id = threading.get_ident()

    started = time.monotonic()
    loop.start()
    assert time.monotonic() - started < 0.2
    deadline = time.monotonic() + 0.5
    while source.connect_thread_id is None and time.monotonic() < deadline:
        time.sleep(0.01)
    source.release.set()
    token.set()
    assert loop.wait(1000)

    assert source.connect_thread_id is not None
    assert source.connect_thread_id != caller_thread_id


def test_unexpected_fetch_exception_emits_status_backs_off_and_recovers() -> None:
    source = _UnexpectedThenReadySource()
    token = CancelToken()
    statuses: list[str] = []
    loop = RefreshLoop(source, n_bars=10, interval_ms=5, cancel_token=token)
    loop.status_changed.connect(statuses.append, Qt.ConnectionType.DirectConnection)
    loop._BACKOFF_BASE_S = 0.05
    loop._MAX_BACKOFF_S = 0.05
    loop.status_changed.connect(statuses.append)

    started = time.monotonic()
    loop.start()
    assert source.ready.wait(timeout=1.0)
    elapsed = time.monotonic() - started
    deadline = time.monotonic() + 0.5
    while not statuses and time.monotonic() < deadline:
        from PyQt6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        time.sleep(0.005)
    token.set()
    assert loop.wait(1000)

    assert elapsed >= 0.04
    assert any("数据刷新异常" in status for status in statuses)
    assert source.fetch_calls >= 2

