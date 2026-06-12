"""Unit tests for keep-analysis tracking schedule helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from pa_agent.config.settings import Settings
from pa_agent.config.tracking_schedule import (
    describe_tracking_window,
    format_tracking_window_hint,
    is_overnight_window,
    is_within_time_window,
    keep_analysis_status_text,
    keep_analysis_tracking_allowed,
    parse_hhmm,
)


def _ms_at(hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 6, 10, hour, minute).timestamp() * 1000)


def test_parse_hhmm_valid():
    assert parse_hhmm("09:30") == (9, 30)
    assert parse_hhmm("9:05") == (9, 5)


def test_parse_hhmm_invalid():
    assert parse_hhmm("") == (9, 0)
    assert parse_hhmm("25:00") == (9, 0)
    assert parse_hhmm("bad") == (9, 0)


def test_within_same_day_window():
    assert is_within_time_window("09:00", "17:00", now_ms=_ms_at(10))
    assert not is_within_time_window("09:00", "17:00", now_ms=_ms_at(8))
    assert not is_within_time_window("09:00", "17:00", now_ms=_ms_at(17))


def test_within_overnight_window():
    assert is_within_time_window("22:00", "06:00", now_ms=_ms_at(23))
    assert is_within_time_window("22:00", "06:00", now_ms=_ms_at(5))
    assert not is_within_time_window("22:00", "06:00", now_ms=_ms_at(12))


def test_within_08_to_next_day_02_local():
    """08:00–02:00 in host local time."""
    assert is_overnight_window("08:00", "02:00")
    assert is_within_time_window("08:00", "02:00", now_ms=_ms_at(8))
    assert is_within_time_window("08:00", "02:00", now_ms=_ms_at(12))
    assert is_within_time_window("08:00", "02:00", now_ms=_ms_at(23))
    assert is_within_time_window("08:00", "02:00", now_ms=_ms_at(1))
    assert not is_within_time_window("08:00", "02:00", now_ms=_ms_at(2))
    assert not is_within_time_window("08:00", "02:00", now_ms=_ms_at(3))
    assert not is_within_time_window("08:00", "02:00", now_ms=_ms_at(7))


def test_describe_overnight_window():
    assert "次日" in describe_tracking_window("08:00", "02:00")
    assert "同一天" in describe_tracking_window("09:00", "17:00")


def test_format_tracking_window_hint_includes_broker_conversion():
    import calendar
    import time
    from datetime import datetime, timezone

    src = MagicMock()
    # Beijing 18:00 = UTC 10:00; broker GMT+3 wall = 13:00 encoded as fake UTC
    local_ms = int(
        datetime(2026, 6, 11, 18, 0, tzinfo=timezone(timedelta(hours=8))).timestamp()
        * 1000
    )
    server_ms = int(calendar.timegm(datetime(2026, 6, 11, 13, 0).timetuple()) * 1000)
    src.server_time_ms.return_value = server_ms

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(time, "time", lambda: local_ms / 1000.0)
        hint = format_tracking_window_hint("08:00", "02:00", data_source=src)

    assert "本机时区" in hint
    assert "经纪商" in hint
    assert "03:00" in hint


def test_keep_analysis_status_text_states():
    settings = Settings()
    now = _ms_at(10)

    visible, text, _ = keep_analysis_status_text(
        keep_analysis_enabled=False,
        settings=settings,
        has_active_position=False,
        analysis_in_progress=False,
        waiting_bar_close=False,
    )
    assert not visible

    visible, text, _ = keep_analysis_status_text(
        keep_analysis_enabled=True,
        settings=settings,
        has_active_position=False,
        analysis_in_progress=False,
        waiting_bar_close=False,
    )
    assert visible and text == "持续跟踪中"

    settings.general.keep_analysis_time_window_enabled = True
    settings.general.keep_analysis_time_start = "09:00"
    settings.general.keep_analysis_time_end = "17:00"
    visible, text, _ = keep_analysis_status_text(
        keep_analysis_enabled=True,
        settings=settings,
        now_ms=_ms_at(7),
        has_active_position=False,
        analysis_in_progress=False,
        waiting_bar_close=False,
    )
    assert visible and "非跟踪时段" in text

    visible, text, _ = keep_analysis_status_text(
        keep_analysis_enabled=True,
        settings=settings,
        now_ms=now,
        has_active_position=False,
        analysis_in_progress=True,
        waiting_bar_close=False,
    )
    assert "分析进行中" in text


def test_tracking_allowed_disabled_by_default():
    settings = Settings()
    assert keep_analysis_tracking_allowed(settings, now_ms=_ms_at(3), has_active_position=False)


def test_tracking_allowed_window_blocks_without_position():
    settings = Settings()
    settings.general.keep_analysis_time_window_enabled = True
    settings.general.keep_analysis_time_start = "09:00"
    settings.general.keep_analysis_time_end = "17:00"
    assert not keep_analysis_tracking_allowed(
        settings, now_ms=_ms_at(8), has_active_position=False
    )
    assert keep_analysis_tracking_allowed(
        settings, now_ms=_ms_at(10), has_active_position=False
    )


def test_tracking_allowed_position_bypass():
    settings = Settings()
    settings.general.keep_analysis_time_window_enabled = True
    settings.general.keep_analysis_time_start = "09:00"
    settings.general.keep_analysis_time_end = "17:00"
    assert keep_analysis_tracking_allowed(
        settings, now_ms=_ms_at(8), has_active_position=True
    )
