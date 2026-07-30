"""Unit tests for shared pending-order trigger semantics."""
from __future__ import annotations

import pytest

from pa_agent.positions.order_trigger import evaluate_order_trigger


@pytest.mark.parametrize(
    ("order_type", "is_long", "open_", "high", "low", "expected_fill", "gap"),
    [
        ("限价单", True, 98.0, 99.0, 97.0, 98.0, True),
        ("限价单", False, 102.0, 103.0, 101.0, 102.0, True),
        ("突破单", True, 102.0, 103.0, 101.0, 102.0, True),
        ("突破单", False, 98.0, 99.0, 97.0, 98.0, True),
    ],
)
def test_gap_through_trigger_uses_observed_open(
    order_type: str,
    is_long: bool,
    open_: float,
    high: float,
    low: float,
    expected_fill: float,
    gap: bool,
) -> None:
    result = evaluate_order_trigger(
        order_type=order_type,
        is_long=is_long,
        entry=100.0,
        bar_open=open_,
        bar_high=high,
        bar_low=low,
        bar_close=open_,
        armed=True,
        previous_price=101.0 if is_long == (order_type == "限价单") else 99.0,
    )

    assert result.triggered is True
    assert result.gap_through is gap
    assert result.fill_price == expected_fill


@pytest.mark.parametrize(
    ("order_type", "is_long", "previous_price", "close"),
    [
        ("限价单", True, 101.0, 99.5),
        ("限价单", False, 99.0, 100.5),
        ("突破单", True, 99.0, 100.5),
        ("突破单", False, 101.0, 99.5),
    ],
)
def test_normal_cross_triggers_at_planned_entry(
    order_type: str,
    is_long: bool,
    previous_price: float,
    close: float,
) -> None:
    result = evaluate_order_trigger(
        order_type=order_type,
        is_long=is_long,
        entry=100.0,
        bar_open=previous_price,
        bar_high=max(previous_price, close, 100.0),
        bar_low=min(previous_price, close, 100.0),
        bar_close=close,
        armed=True,
        previous_price=previous_price,
    )
    assert result.triggered is True
    assert result.gap_through is False
    assert result.fill_price == 100.0


def test_unarmed_historical_range_does_not_create_false_fill() -> None:
    result = evaluate_order_trigger(
        order_type="突破单",
        is_long=True,
        entry=100.0,
        bar_open=99.0,
        bar_high=101.0,
        bar_low=98.0,
        bar_close=100.5,
        armed=False,
        previous_price=None,
    )
    assert result.triggered is False
