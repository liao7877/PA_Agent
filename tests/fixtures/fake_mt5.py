"""Deterministic fake MetaTrader5 module for offline tests."""
from __future__ import annotations

import threading
from collections import deque
from types import SimpleNamespace
from typing import Any


class FakeMT5:
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15

    def __init__(self) -> None:
        self.initialize_results: deque[bool] = deque([True])
        self.terminal_connected = True
        self.account_available = True
        self.symbols: dict[str, Any] = {
            "XAUUSD": SimpleNamespace(name="XAUUSD"),
            "EURUSD": SimpleNamespace(name="EURUSD"),
        }
        self.symbol_select_results: dict[str, bool] = {}
        self.rates: Any = []
        self.tick: Any = None
        self.error: tuple[int, str] = (0, "ok")
        self.initialize_calls: list[dict[str, Any]] = []
        self.shutdown_calls = 0
        self.symbol_select_calls: list[tuple[str, bool]] = []
        self.call_thread_ids: list[int] = []
        self.active_calls = 0
        self.max_active_calls = 0
        self._call_lock = threading.Lock()

    def _record(self) -> None:
        with self._call_lock:
            self.call_thread_ids.append(threading.get_ident())
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            self.active_calls -= 1

    def initialize(self, **kwargs: Any) -> bool:
        self._record()
        self.initialize_calls.append(dict(kwargs))
        result = self.initialize_results.popleft() if len(self.initialize_results) > 1 else self.initialize_results[0]
        if not result:
            self.error = (-6, "Terminal: Authorization failed")
        return result

    def shutdown(self) -> None:
        self._record()
        self.shutdown_calls += 1

    def terminal_info(self) -> Any:
        self._record()
        return SimpleNamespace(
            name="Fake MT5",
            build=5000,
            connected=self.terminal_connected,
            path="C:/Fake/terminal64.exe",
        )

    def account_info(self) -> Any:
        self._record()
        if not self.account_available:
            return None
        return SimpleNamespace(login=123456, server="Fake-Server")

    def last_error(self) -> tuple[int, str]:
        self._record()
        return self.error

    def symbol_info(self, symbol: str) -> Any:
        self._record()
        return self.symbols.get(symbol)

    def symbol_select(self, symbol: str, selected: bool) -> bool:
        self._record()
        self.symbol_select_calls.append((symbol, selected))
        return self.symbol_select_results.get(symbol, symbol in self.symbols)

    def symbols_get(self) -> tuple[Any, ...]:
        self._record()
        return tuple(self.symbols.values())

    def symbol_info_tick(self, symbol: str) -> Any:
        self._record()
        return self.tick

    def copy_rates_from_pos(
        self,
        symbol: str,
        timeframe: int,
        start_pos: int,
        count: int,
    ) -> Any:
        self._record()
        return self.rates
