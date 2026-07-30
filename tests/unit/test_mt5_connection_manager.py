"""Regression tests for the process-wide MT5 connection owner."""
from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from pa_agent.data.base import DataSourceTransientError
from tests.fixtures.fake_mt5 import FakeMT5


@pytest.fixture
def fake_mt5(monkeypatch: pytest.MonkeyPatch) -> FakeMT5:
    fake = FakeMT5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    return fake


def test_acquire_retries_authorization_and_commits_lease_only_after_ready(fake_mt5: FakeMT5) -> None:
    from pa_agent.data.mt5_connection_manager import MT5ConnectionManager

    fake_mt5.initialize_results.clear()
    fake_mt5.initialize_results.extend([False, False, True])
    manager = MT5ConnectionManager(
        initialize_attempts=3,
        backoff_initial_s=0,
        backoff_max_s=0,
        request_timeout_s=2,
    )

    manager.acquire("source-a")

    assert manager.is_ready is True
    assert manager.lease_count == 1
    assert len(fake_mt5.initialize_calls) == 3
    manager.force_shutdown()


def test_failed_acquire_does_not_leak_lease(fake_mt5: FakeMT5) -> None:
    from pa_agent.data.mt5_connection_manager import MT5ConnectionManager

    fake_mt5.initialize_results.clear()
    fake_mt5.initialize_results.append(False)
    manager = MT5ConnectionManager(
        initialize_attempts=2,
        backoff_initial_s=0,
        backoff_max_s=0,
        request_timeout_s=2,
    )

    with pytest.raises(DataSourceTransientError, match="Authorization failed"):
        manager.acquire("source-a")

    assert manager.lease_count == 0
    assert manager.is_ready is False
    manager.force_shutdown()


@pytest.mark.parametrize(
    ("terminal_connected", "account_available", "message"),
    [
        (False, True, "not connected"),
        (True, False, "account"),
    ],
)
def test_readiness_requires_connected_terminal_and_account(
    fake_mt5: FakeMT5,
    terminal_connected: bool,
    account_available: bool,
    message: str,
) -> None:
    from pa_agent.data.mt5_connection_manager import MT5ConnectionManager

    fake_mt5.terminal_connected = terminal_connected
    fake_mt5.account_available = account_available
    manager = MT5ConnectionManager(
        initialize_attempts=1,
        backoff_initial_s=0,
        request_timeout_s=2,
    )

    with pytest.raises(DataSourceTransientError, match=message):
        manager.acquire("source-a")

    assert manager.lease_count == 0
    manager.force_shutdown()


def test_two_leases_share_one_initialize_and_last_release_shuts_down(fake_mt5: FakeMT5) -> None:
    from pa_agent.data.mt5_connection_manager import MT5ConnectionManager

    manager = MT5ConnectionManager(request_timeout_s=2)

    manager.acquire("source-a")
    manager.acquire("source-b")
    manager.release("source-a")

    assert len(fake_mt5.initialize_calls) == 1
    assert fake_mt5.shutdown_calls == 0
    assert manager.lease_count == 1

    manager.release("source-b")

    assert fake_mt5.shutdown_calls == 1
    assert manager.lease_count == 0
    manager.stop()


def test_symbol_selection_false_is_explicit_error(fake_mt5: FakeMT5) -> None:
    from pa_agent.data.mt5_connection_manager import MT5ConnectionManager

    fake_mt5.symbol_select_results["XAUUSD"] = False
    fake_mt5.error = (-1, "symbol disabled")
    manager = MT5ConnectionManager(request_timeout_s=2)
    manager.acquire("source-a")

    with pytest.raises(DataSourceTransientError, match="symbol_select.*XAUUSD"):
        manager.ensure_symbol_selected("XAUUSD")

    manager.force_shutdown()


def test_all_mt5_calls_are_serialized_on_one_worker_thread(fake_mt5: FakeMT5) -> None:
    from pa_agent.data.mt5_connection_manager import MT5ConnectionManager

    manager = MT5ConnectionManager(request_timeout_s=2)
    manager.acquire("source-a")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(manager.symbol_exists, ["XAUUSD", "EURUSD"] * 10))

    assert all(results)
    assert len(set(fake_mt5.call_thread_ids)) == 1
    assert fake_mt5.call_thread_ids[0] != threading.get_ident()
    assert fake_mt5.max_active_calls == 1
    manager.force_shutdown()


def test_timed_out_queued_request_is_not_executed_later(fake_mt5: FakeMT5) -> None:
    from pa_agent.data.mt5_connection_manager import MT5ConnectionManager

    manager = MT5ConnectionManager(request_timeout_s=0.1)
    blocker_started = threading.Event()
    release_blocker = threading.Event()
    stale_executed = threading.Event()

    def blocker() -> None:
        blocker_started.set()
        release_blocker.wait(timeout=1.0)

    first_errors: list[BaseException] = []

    def submit_blocker() -> None:
        try:
            manager._submit(blocker)
        except BaseException as exc:  # noqa: BLE001
            first_errors.append(exc)

    first = threading.Thread(target=submit_blocker)
    first.start()
    assert blocker_started.wait(timeout=0.5)

    with pytest.raises(DataSourceTransientError, match="timed out"):
        manager._submit(stale_executed.set)

    release_blocker.set()
    first.join(timeout=1.0)
    time.sleep(0.05)
    assert not stale_executed.is_set()
    assert all(isinstance(exc, DataSourceTransientError) for exc in first_errors)
    assert manager.is_worker_alive
    manager.force_shutdown()


def test_timed_out_inflight_request_does_not_kill_owner_worker(fake_mt5: FakeMT5) -> None:
    from pa_agent.data.mt5_connection_manager import MT5ConnectionManager

    manager = MT5ConnectionManager(request_timeout_s=0.1)
    release = threading.Event()

    with pytest.raises(DataSourceTransientError, match="timed out"):
        manager._submit(lambda: release.wait(timeout=0.3))
    release.set()
    time.sleep(0.05)

    assert manager.is_worker_alive
    assert manager._submit(lambda: "ok") == "ok"
    manager.force_shutdown()

