"""Local timezone detection and broker clock conversion helpers."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, time as dt_time, timezone

from pa_agent.data.datetime_ts import _EPOCH

_MINUTES_PER_DAY = 24 * 60


def now_local_ms() -> int:
    """Current instant as real UTC epoch milliseconds (host clock)."""
    return int(time.time() * 1000)


def local_timezone() -> timezone:
    """Host local timezone (DST-aware when the OS provides it)."""
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def format_utc_offset(offset: timedelta | None) -> str:
    """Format a fixed offset as ``UTC+3`` / ``UTC+5:30`` / ``UTC-5``."""
    if offset is None:
        return "UTC"
    total_sec = int(offset.total_seconds())
    sign = "+" if total_sec >= 0 else "-"
    total_sec = abs(total_sec)
    hours, rem = divmod(total_sec, 3600)
    minutes = rem // 60
    if minutes == 0:
        return f"UTC{sign}{hours}"
    return f"UTC{sign}{hours}:{minutes:02d}"


def local_timezone_label() -> str:
    """Human label for the host timezone, e.g. ``Asia/Shanghai (UTC+8)``."""
    tz = local_timezone()
    now = datetime.now(tz)
    offset = now.utcoffset() or timedelta(0)
    name = now.tzname() or getattr(tz, "key", None) or "Local"
    return f"{name} ({format_utc_offset(offset)})"


def local_wall_time(now_ms: int | None = None) -> dt_time:
    """Wall-clock time in the host local timezone for a real UTC epoch."""
    if now_ms is None:
        now_ms = now_local_ms()
    return datetime.fromtimestamp(now_ms / 1000.0).astimezone().time()


def hhmm_to_minutes(hhmm: str, *, default: tuple[int, int] = (0, 0)) -> int:
    text = (hhmm or "").strip()
    parts = text.split(":", 1)
    if len(parts) != 2:
        hour, minute = default
    else:
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            hour, minute = default
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        hour, minute = default
    return hour * 60 + minute


def minutes_to_hhmm(minutes: int) -> str:
    minutes %= _MINUTES_PER_DAY
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def convert_hhmm_between_offsets(
    hhmm: str,
    from_offset: timedelta,
    to_offset: timedelta,
) -> str:
    """Convert ``HH:MM`` wall clock from one fixed UTC offset to another."""
    wall_sec = hhmm_to_minutes(hhmm) * 60
    utc_sec = wall_sec - int(from_offset.total_seconds())
    target_sec = utc_sec + int(to_offset.total_seconds())
    target_sec %= 24 * 3600
    if target_sec < 0:
        target_sec += 24 * 3600
    return minutes_to_hhmm(target_sec // 60)


def detect_broker_utc_offset(data_source: object | None) -> timedelta | None:
    """Detect broker/server UTC offset from a live MT5 tick, if available."""
    if data_source is None:
        return None
    server_time_ms = getattr(data_source, "server_time_ms", None)
    if not callable(server_time_ms):
        return None
    try:
        server_ms = server_time_ms()
    except Exception:  # noqa: BLE001
        return None
    if server_ms is None:
        return None

    local_ms = now_local_ms()
    utc_naive = datetime.fromtimestamp(local_ms / 1000.0, tz=timezone.utc).replace(
        tzinfo=None
    )
    server_naive = _EPOCH + timedelta(milliseconds=int(server_ms))
    broker_offset_sec = int(round((server_naive - utc_naive).total_seconds()))
    # Brokers use whole-hour offsets; snap noise from tick latency.
    snapped = int(round(broker_offset_sec / 3600.0) * 3600)
    return timedelta(seconds=snapped)


def broker_timezone_label(data_source: object | None) -> str | None:
    """Label for broker clock when MT5 is connected, else ``None``."""
    offset = detect_broker_utc_offset(data_source)
    if offset is None:
        return None
    return f"经纪商 ({format_utc_offset(offset)})"
