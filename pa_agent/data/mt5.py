"""MetaTrader 5 data source.

Requires MetaTrader 5 terminal to be installed and running on Windows.
Install the Python package: pip install MetaTrader5

Usage:
    source = MT5Source()
    source.connect()                        # connects to running MT5 terminal
    source.subscribe("XAUUSD", "1h")
    bars = source.latest_snapshot(200)      # newest-first, bars[0] = forming bar
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pa_agent.data.base import (
    DataSource,
    DataSourceTransientError,
    KlineBar,
    normalize_kline_bar,
)

logger = logging.getLogger(__name__)

# Map our timeframe strings → MT5 TIMEFRAME constants (by name)
_TF_MAP: dict[str, str] = {
    "1m":  "TIMEFRAME_M1",
    "2m":  "TIMEFRAME_M2",
    "3m":  "TIMEFRAME_M3",
    "5m":  "TIMEFRAME_M5",
    "10m": "TIMEFRAME_M10",
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1h":  "TIMEFRAME_H1",
    "2h":  "TIMEFRAME_H2",
    "3h":  "TIMEFRAME_H3",
    "4h":  "TIMEFRAME_H4",
    "6h":  "TIMEFRAME_H6",
    "8h":  "TIMEFRAME_H8",
    "12h": "TIMEFRAME_H12",
    "1d":  "TIMEFRAME_D1",
    "1w":  "TIMEFRAME_W1",
    "1M":  "TIMEFRAME_MN1",
}


def resolve_mt5_terminal_executable(path: str) -> str | None:
    """Resolve user config to ``terminal64.exe`` path for ``mt5.initialize(path=...)``."""
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        return None
    p = Path(raw)
    if p.is_file():
        return str(p.resolve())
    if p.is_dir():
        for name in ("terminal64.exe", "terminal.exe"):
            candidate = p / name
            if candidate.is_file():
                return str(candidate.resolve())
        candidate = p / "terminal64.exe"
        return str(candidate)
    if raw.lower().endswith(".exe"):
        return raw
    return str(Path(raw) / "terminal64.exe")


class MT5Source(DataSource):
    """Live K-line data from MetaTrader 5 terminal.

    Zero latency — data comes directly from your broker via the MT5 terminal.
    MT5 terminal must be open and logged in before calling connect().
    """

    def __init__(self, terminal_path: str = "", *, manager: Any = None) -> None:
        self._symbol: str = ""
        self._timeframe: str = ""
        self._connected: bool = False
        self._terminal_path = terminal_path
        self._manager = manager
        self._lease_id = f"mt5-source-{uuid.uuid4().hex}"

    def _connection_manager(self) -> Any:
        if self._manager is None:
            from pa_agent.data.mt5_connection_manager import get_mt5_connection_manager

            self._manager = get_mt5_connection_manager()
        return self._manager

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Acquire a lease on the process-wide MT5 connection."""
        if self._connected:
            return
        self._connection_manager().acquire(self._lease_id, self._terminal_path)
        self._connected = True
        logger.info("MT5Source connected through process-wide owner")

    def disconnect(self) -> None:
        """Release this source without disrupting other MT5 users."""
        try:
            if self._manager is not None and self._symbol:
                self._manager.remove_symbol(self._lease_id, self._symbol)
            if self._connected:
                self._connection_manager().release(self._lease_id)
        finally:
            self._connected = False
        logger.info("MT5Source disconnected")

    # ── Discovery ─────────────────────────────────────────────────────────────

    def is_symbol_available(self, symbol: str) -> bool:
        """Return True if *symbol* exists in the connected MT5 terminal."""
        name = (symbol or "").strip()
        if not name:
            return False
        if not self._connected:
            return False
        try:
            return self._connection_manager().symbol_exists(name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("MT5 symbol_info(%s) failed: %s", name, exc)
            return False

    def list_symbols(self) -> list[str]:
        """Return all symbols available in the MT5 terminal."""
        if not self._connected:
            return []
        try:
            return self._connection_manager().list_symbols()
        except Exception as exc:  # noqa: BLE001
            logger.warning("MT5 list_symbols failed: %s", exc)
        return []

    def supported_timeframes(self) -> list[str]:
        return list(_TF_MAP.keys())

    # ── Subscription ──────────────────────────────────────────────────────────

    def subscribe(self, symbol: str, timeframe: str) -> None:
        if timeframe not in _TF_MAP:
            raise ValueError(
                f"Unsupported timeframe: {timeframe!r}. "
                f"Use one of {list(_TF_MAP)}"
            )
        name = str(symbol or "").strip()
        if not name:
            raise DataSourceTransientError("MT5 symbol is empty")
        old_symbol = self._symbol
        if self._connected:
            # Validate/select before changing local state so a failed resubscribe keeps
            # the previous working subscription intact.
            self._connection_manager().ensure_symbol_selected(self._lease_id, name)
            if old_symbol and old_symbol != name:
                self._connection_manager().remove_symbol(self._lease_id, old_symbol)
        self._symbol = name
        self._timeframe = timeframe
        logger.info("MT5Source subscribed: %s %s", name, timeframe)

    def unsubscribe(self) -> None:
        if self._manager is not None and self._symbol:
            self._manager.remove_symbol(self._lease_id, self._symbol)
        self._symbol = ""
        self._timeframe = ""
        logger.info("MT5Source unsubscribed")

    def server_time_ms(self, symbol: str | None = None) -> int | None:
        """Broker/server time from the latest MT5 tick (milliseconds since epoch).

        Use this for forming-bar countdowns so ``now`` matches ``rate['time']``
        on K-line bars. Falls back to None when disconnected or tick unavailable.
        """
        if not self._connected:
            return None
        name = (symbol or self._symbol or "").strip()
        if not name:
            return None
        try:
            tick = self._connection_manager().symbol_tick(name)
            if tick is None:
                return None
            time_msc = getattr(tick, "time_msc", None)
            if time_msc:
                return int(time_msc)
            tick_time = getattr(tick, "time", None)
            if tick_time:
                return int(tick_time) * 1000
        except Exception as exc:  # noqa: BLE001
            logger.debug("MT5 server_time_ms(%s) failed: %s", name, exc)
        return None

    # ── Data fetch ────────────────────────────────────────────────────────────

    def latest_snapshot(self, n: int) -> list[KlineBar]:
        """Return *n* bars newest-first; bars[0] is the forming (unclosed) bar.

        Uses copy_rates_from_pos(symbol, timeframe, 0, n+1):
        - position 0 = current forming bar
        - position 1..n = closed bars
        """
        if not self._connected:
            raise DataSourceTransientError("Not connected — call connect() first")
        if not self._symbol or not self._timeframe:
            raise DataSourceTransientError("Not subscribed — call subscribe() first")

        tf_name = _TF_MAP[self._timeframe]
        tf_const = self._connection_manager().timeframe_constant(tf_name)
        rates = self._connection_manager().copy_rates_from_pos(
            self._symbol,
            tf_const,
            0,
            n + 1,
        )

        # copy_rates_from_pos returns oldest-first (ascending time order).
        # rates[0] is the OLDEST bar, rates[-1] is the NEWEST (forming) bar.
        # We need newest-first, so reverse the array before building KlineBar list.
        bars: list[KlineBar] = []
        for i, rate in enumerate(reversed(rates)):
            # rate fields: time, open, high, low, close, tick_volume, spread, real_volume
            ts_ms = int(rate["time"]) * 1000  # MT5 gives UTC seconds
            try:
                vol = float(rate["tick_volume"])
            except (ValueError, KeyError):
                try:
                    vol = float(rate["real_volume"])
                except (ValueError, KeyError):
                    vol = 0.0
            bars.append(
                normalize_kline_bar(
                    KlineBar(
                        seq=i + 1,
                        ts_open=ts_ms,
                        open=float(rate["open"]),
                        high=float(rate["high"]),
                        low=float(rate["low"]),
                        close=float(rate["close"]),
                        volume=vol,
                        closed=(i != 0),  # i=0 is the newest (forming) bar
                    )
                )
            )
            if len(bars) >= n:
                break

        return bars
