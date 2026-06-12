"""Unit tests for local timezone and broker offset helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from pa_agent.util.local_tz import (
    convert_hhmm_between_offsets,
    detect_broker_utc_offset,
    format_utc_offset,
    hhmm_to_minutes,
    minutes_to_hhmm,
)


def test_convert_hhmm_beijing_to_gmt3():
    beijing = timedelta(hours=8)
    broker = timedelta(hours=3)
    assert convert_hhmm_between_offsets("08:00", beijing, broker) == "03:00"
    assert convert_hhmm_between_offsets("02:00", beijing, broker) == "21:00"


def test_detect_broker_utc_offset_from_mock_tick():
    # Real UTC 16:49 -> Beijing 00:49 next day; broker wall 19:49 (GMT+3)
    import calendar
    import time

    local_ms = int(datetime(2026, 6, 11, 0, 49, 47, tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000)
    server_ms = int(calendar.timegm(datetime(2026, 6, 10, 19, 49, 48).timetuple()) * 1000)

    src = MagicMock()
    src.server_time_ms.return_value = server_ms

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(time, "time", lambda: local_ms / 1000.0)
        offset = detect_broker_utc_offset(src)

    assert offset == timedelta(hours=3)


def test_hhmm_roundtrip():
    assert minutes_to_hhmm(hhmm_to_minutes("08:30")) == "08:30"
    assert format_utc_offset(timedelta(hours=8)) == "UTC+8"
    assert format_utc_offset(timedelta(hours=3)) == "UTC+3"
    assert format_utc_offset(timedelta(hours=5, minutes=30)) == "UTC+5:30"
