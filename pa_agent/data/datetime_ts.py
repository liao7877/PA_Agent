"""Timezone-safe datetime ↔ epoch helpers for market data sources."""
from __future__ import annotations

import calendar
import time as _time
from datetime import datetime, time, timedelta, timezone

_EPOCH = datetime(1970, 1, 1)


def naive_local_to_utc(dt: datetime) -> datetime:
    """Interpret naive *dt* as local wall time and convert to UTC."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    local_offset = timedelta(seconds=-_time.timezone)
    return dt.replace(tzinfo=timezone(local_offset)).astimezone(timezone.utc)


def datetime_to_ts_ms(dt: object) -> int:
    """Convert a datetime or pandas Timestamp to epoch milliseconds (UTC).

  - Timezone-aware values are converted to UTC before epoch conversion.
  - Naive values are treated as UTC wall clock (no ``datetime.timestamp()`` local
    shift), matching MT5 server-time semantics used elsewhere in the project.
    """
    if dt is None:
        return int(_time.time() * 1000)

    try:
        import pandas as pd

        if isinstance(dt, pd.Timestamp):
            ts = dt
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            return int(ts.timestamp() * 1000)
    except ImportError:
        pass

    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return int(dt.timestamp() * 1000)
        return int(calendar.timegm(dt.timetuple())) * 1000

    text = str(dt).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return int(_time.time() * 1000)
    return datetime_to_ts_ms(parsed)


def ts_open_to_ms(ts_open: float) -> float:
    """Normalize bar open time to epoch milliseconds (canonical ``KlineBar.ts_open``)."""
    ts = float(ts_open)
    if ts <= 0:
        return ts
    if ts < 1e10:
        return ts * 1000.0
    return ts


def format_epoch_for_display(ts_open: float, *, short: bool = False) -> str:
    """Format bar open epoch without applying the host local timezone offset."""
    sec = float(ts_open)
    if sec > 1e12:
        sec /= 1000.0
    fmt = "%Y-%m-%d %H:%M" if short else "%Y-%m-%d %H:%M:%S"
    return (_EPOCH + timedelta(seconds=sec)).strftime(fmt)


def reference_clock_time(now_ms: int, *, server_wall: bool) -> time:
    """Extract HH:MM:SS on the K-line reference clock from epoch milliseconds.

    MT5 broker ticks encode server wall time as naive UTC epoch (``server_wall=True``).
    Local ``time.time()`` uses real UTC and must be converted with ``fromtimestamp``
  (``server_wall=False``).
    """
    sec = float(now_ms) / 1000.0
    if server_wall:
        return (_EPOCH + timedelta(seconds=sec)).time()
    return datetime.fromtimestamp(sec).time()
