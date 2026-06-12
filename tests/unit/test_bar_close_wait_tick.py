"""Tests for closed-bar selection used in position tick checks."""
from __future__ import annotations

from pa_agent.data.bar_close_wait import bar_ts_open_ms, newest_closed_bar_for_tick
from pa_agent.data.base import KlineBar


def _bar(seq: int, *, closed: bool) -> KlineBar:
    return KlineBar(
        seq=seq,
        ts_open=float(1_700_000_000_000 + seq),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=1.0,
        closed=closed,
    )


def test_newest_closed_bar_skips_forming_head() -> None:
    bars = [_bar(0, closed=False), _bar(1, closed=True), _bar(2, closed=True)]
    got = newest_closed_bar_for_tick(bars)
    assert got is bars[1]
    assert bar_ts_open_ms(got) == 1_700_000_000_001


def test_newest_closed_bar_when_head_is_closed() -> None:
    bars = [_bar(1, closed=True), _bar(2, closed=True)]
    got = newest_closed_bar_for_tick(bars)
    assert got is bars[0]
