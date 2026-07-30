"""Behavioral tests for owner-backed MT5Source."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from pa_agent.data.base import DataSourceTransientError
from pa_agent.data.mt5 import MT5Source
from tests.fixtures.fake_mt5 import FakeMT5


@pytest.fixture
def fake_mt5(monkeypatch: pytest.MonkeyPatch) -> FakeMT5:
    from pa_agent.data.mt5_connection_manager import reset_mt5_connection_manager

    reset_mt5_connection_manager()
    fake = FakeMT5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    yield fake
    reset_mt5_connection_manager()


def _rates() -> list[dict[str, float]]:
    return [
        {"time": 1_700_000_100, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "tick_volume": 10, "real_volume": 0},
        {"time": 1_700_000_200, "open": 10.5, "high": 12.0, "low": 10.0, "close": 11.5, "tick_volume": 20, "real_volume": 0},
        {"time": 1_700_000_300, "open": 11.5, "high": 13.0, "low": 11.0, "close": 12.0, "tick_volume": 30, "real_volume": 0},
    ]


def test_two_sources_share_connection_and_one_disconnect_does_not_break_other(fake_mt5: FakeMT5) -> None:
    fake_mt5.rates = _rates()
    first = MT5Source()
    second = MT5Source()

    first.connect()
    second.connect()
    first.subscribe("XAUUSD", "5m")
    second.subscribe("EURUSD", "5m")
    first.disconnect()

    bars = second.latest_snapshot(2)

    assert len(fake_mt5.initialize_calls) == 1
    assert fake_mt5.shutdown_calls == 0
    assert [bar.ts_open for bar in bars] == [1_700_000_300_000, 1_700_000_200_000]
    assert bars[0].closed is False
    second.disconnect()
    assert fake_mt5.shutdown_calls == 1


def test_snapshot_reconnects_after_session_loss(fake_mt5: FakeMT5) -> None:
    fake_mt5.rates = _rates()
    source = MT5Source()
    source.connect()
    source.subscribe("XAUUSD", "5m")
    fake_mt5.terminal_connected = False

    original_terminal_info = fake_mt5.terminal_info
    calls = 0

    def recovering_terminal_info():
        nonlocal calls
        calls += 1
        if calls >= 2:
            fake_mt5.terminal_connected = True
        return original_terminal_info()

    fake_mt5.terminal_info = recovering_terminal_info  # type: ignore[method-assign]

    bars = source.latest_snapshot(2)

    assert len(bars) == 2
    assert len(fake_mt5.initialize_calls) >= 2
    source.disconnect()


def test_subscribe_rejects_unavailable_symbol(fake_mt5: FakeMT5) -> None:
    source = MT5Source()
    source.connect()

    with pytest.raises(DataSourceTransientError, match="unavailable.*NOTREAL"):
        source.subscribe("NOTREAL", "5m")

    source.disconnect()


def test_disconnected_source_does_not_assume_symbol_is_available(fake_mt5: FakeMT5) -> None:
    source = MT5Source()
    assert source.is_symbol_available("XAUUSD") is False


def test_server_time_uses_owner_worker(fake_mt5: FakeMT5) -> None:
    fake_mt5.tick = SimpleNamespace(time_msc=1_700_000_123_456, time=0)
    source = MT5Source()
    source.connect()
    source.subscribe("XAUUSD", "5m")

    assert source.server_time_ms() == 1_700_000_123_456
    source.disconnect()


def test_two_sources_same_symbol_reselect_after_one_unsubscribes(fake_mt5: FakeMT5) -> None:
    first = MT5Source()
    second = MT5Source()
    first.connect()
    second.connect()
    first.subscribe("XAUUSD", "5m")
    second.subscribe("XAUUSD", "5m")

    first.unsubscribe()
    fake_mt5.terminal_connected = False
    calls = 0
    original = fake_mt5.terminal_info

    def recover():
        nonlocal calls
        calls += 1
        if calls >= 2:
            fake_mt5.terminal_connected = True
        return original()

    fake_mt5.terminal_info = recover  # type: ignore[method-assign]
    second.server_time_ms("XAUUSD")

    assert fake_mt5.symbol_select_calls.count(("XAUUSD", True)) >= 2
    first.disconnect()
    second.disconnect()


def test_resubscribe_releases_old_symbol(fake_mt5: FakeMT5) -> None:
    source = MT5Source()
    source.connect()
    source.subscribe("XAUUSD", "5m")
    source.subscribe("EURUSD", "5m")

    manager = source._connection_manager()
    assert "XAUUSD" not in manager._symbol_holders
    assert manager._symbol_holders["EURUSD"] == {source._lease_id}
    source.disconnect()

