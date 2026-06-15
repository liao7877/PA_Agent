"""Time-window helpers for scheduled keep-analysis tracking."""
from __future__ import annotations

from datetime import datetime, time, timedelta
import re

from pa_agent.config.settings import GeneralSettings, Settings
from pa_agent.util.local_tz import (
    convert_hhmm_between_offsets,
    detect_broker_utc_offset,
    format_utc_offset,
    local_timezone_label,
    local_wall_time,
    now_local_ms,
)

_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_hhmm(value: str, *, default: tuple[int, int] = (9, 0)) -> tuple[int, int]:
    """Parse ``HH:MM`` into (hour, minute); invalid input returns *default*."""
    text = (value or "").strip()
    match = _HHMM_RE.match(text)
    if not match:
        return default
    hour = int(match.group(1))
    minute = int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return hour, minute


def time_from_hhmm(value: str, *, default: tuple[int, int] = (9, 0)) -> time:
    hour, minute = parse_hhmm(value, default=default)
    return time(hour=hour, minute=minute)


def is_overnight_window(start_hhmm: str, end_hhmm: str) -> bool:
    """True when end is earlier on the clock than start (spans midnight)."""
    start = time_from_hhmm(start_hhmm, default=(9, 0))
    end = time_from_hhmm(end_hhmm, default=(23, 0))
    if start == end:
        return False
    return start > end


def is_within_time_window(
    start_hhmm: str,
    end_hhmm: str,
    *,
    now_ms: int | None = None,
) -> bool:
    """Return True when the current **local** wall clock is inside the window.

    Configured ``HH:MM`` values are interpreted in the host local timezone.
    Same-day window: ``[start, end)`` — e.g. 09:00–17:00.
    Overnight window: ``[start, 24:00) ∪ [00:00, end)`` — e.g. 08:00–02:00 means
    from 08:00 today through 01:59 next calendar day (02:00 is excluded).
    """
    start = time_from_hhmm(start_hhmm, default=(9, 0))
    end = time_from_hhmm(end_hhmm, default=(23, 0))
    current = local_wall_time(now_ms)

    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def describe_tracking_window(start_hhmm: str, end_hhmm: str) -> str:
    """Human-readable description for settings UI."""
    start = (start_hhmm or "09:00").strip()
    end = (end_hhmm or "23:00").strip()
    if is_overnight_window(start, end):
        return f"每日 {start} 至次日 {end}（跨午夜）"
    if start == end:
        return f"每日 {start} 起全天有效"
    return f"每日 {start} 至 {end}（同一天内）"


def format_tracking_window_hint(
    start_hhmm: str,
    end_hhmm: str,
    *,
    data_source: object | None = None,
) -> str:
    """Settings hint: local window plus optional broker-clock conversion."""
    start = (start_hhmm or "09:00").strip()
    end = (end_hhmm or "23:00").strip()
    local_label = local_timezone_label()
    lines = [
        f"含义：{describe_tracking_window(start, end)}（本机时区 {local_label}）",
    ]

    broker_offset = detect_broker_utc_offset(data_source)
    if broker_offset is None:
        return lines[0]

    local_offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    broker_start = convert_hhmm_between_offsets(start, local_offset, broker_offset)
    broker_end = convert_hhmm_between_offsets(end, local_offset, broker_offset)
    broker_overnight = is_overnight_window(broker_start, broker_end)
    end_text = f"次日 {broker_end}" if broker_overnight else broker_end
    sep = "至次日" if broker_overnight else "至"
    broker_label = format_utc_offset(broker_offset)
    lines.append(
        f"已连接 MT5，自动换算为经纪商时钟 {broker_label}："
        f"{broker_start} {sep} {end_text}"
    )
    return "\n".join(lines)


def keep_analysis_tracking_allowed(
    settings: Settings | None,
    *,
    now_ms: int | None = None,
    has_active_position: bool,
) -> bool:
    """Whether keep-analysis may submit analysis at the current local time."""
    if settings is None:
        return True
    general: GeneralSettings = settings.general
    if not bool(getattr(general, "keep_analysis_time_window_enabled", False)):
        return True
    if has_active_position and bool(
        getattr(general, "keep_analysis_bypass_with_position", True)
    ):
        return True
    start = getattr(general, "keep_analysis_time_start", "09:00")
    end = getattr(general, "keep_analysis_time_end", "23:00")
    if now_ms is None:
        now_ms = now_local_ms()
    return is_within_time_window(start, end, now_ms=now_ms)


def keep_analysis_status_text(
    *,
    keep_analysis_enabled: bool,
    settings: Settings | None,
    has_active_position: bool,
    analysis_in_progress: bool,
    waiting_bar_close: bool,
    now_ms: int | None = None,
    data_source: object | None = None,
) -> tuple[bool, str, str]:
    """Return (visible, status_text, tooltip) for the main-window tracking badge."""
    if not keep_analysis_enabled:
        return False, "", ""

    general = getattr(settings, "general", None) if settings is not None else None
    window_enabled = bool(
        getattr(general, "keep_analysis_time_window_enabled", False)
    )
    tracking_allowed = keep_analysis_tracking_allowed(
        settings,
        now_ms=now_ms,
        has_active_position=has_active_position,
    )

    tooltip = format_tracking_window_label(
        settings, data_source=data_source
    ) if window_enabled else (
        "已开启持续跟踪：有新 K 线收盘时自动分析"
    )

    if window_enabled and not tracking_allowed:
        return True, "非跟踪时段中，暂不跟踪", tooltip

    if analysis_in_progress:
        return True, "持续跟踪中 · 分析进行中", tooltip
    if waiting_bar_close:
        return True, "持续跟踪中 · 等待K线收盘", tooltip
    return True, "持续跟踪中", tooltip


def format_tracking_window_label(
    settings: Settings | None,
    *,
    data_source: object | None = None,
) -> str:
    """Human-readable tracking window for tooltips/status."""
    if settings is None:
        return ""
    general = settings.general
    if not bool(getattr(general, "keep_analysis_time_window_enabled", False)):
        return "未限制跟踪时段"
    start = getattr(general, "keep_analysis_time_start", "09:00")
    end = getattr(general, "keep_analysis_time_end", "23:00")
    bypass = "有持仓时不受限" if getattr(
        general, "keep_analysis_bypass_with_position", True
    ) else "有持仓也受限"
    window = describe_tracking_window(start, end)
    local_label = local_timezone_label()
    text = f"{window}（本机 {local_label}，{bypass}）"
    broker_offset = detect_broker_utc_offset(data_source)
    if broker_offset is not None:
        local_offset = datetime.now().astimezone().utcoffset() or timedelta(0)
        broker_start = convert_hhmm_between_offsets(start, local_offset, broker_offset)
        broker_end = convert_hhmm_between_offsets(end, local_offset, broker_offset)
        text += (
            f"；经纪商约 {broker_start}–"
            f"{'次日 ' if is_overnight_window(broker_start, broker_end) else ''}"
            f"{broker_end}"
        )
    return text
