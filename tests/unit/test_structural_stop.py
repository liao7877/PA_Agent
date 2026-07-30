"""Tests for verifiable structural stop anchors."""
from __future__ import annotations

from pa_agent.data.base import IndicatorBundle, KlineBar, KlineFrame
from pa_agent.util.trade_metrics import validate_order_trade_metrics


def _frame() -> KlineFrame:
    return KlineFrame(
        symbol="TEST",
        timeframe="15m",
        bars=(
            KlineBar(seq=1, ts_open=2, open=101.1, high=103.1, low=100.1, close=102.1, volume=1, closed=True),
            KlineBar(seq=2, ts_open=1, open=100.1, high=102.1, low=98.0, close=101.1, volume=1, closed=True),
        ),
        indicators=IndicatorBundle(ema20=(100, 100), atr14=(2, 2)),
        snapshot_ts_local_ms=3,
    )


def _long(stop: float, *, anchor_price: float = 98.0) -> dict:
    return {
        "order_type": "突破单",
        "order_direction": "做多",
        "entry_price": 102.1,
        "stop_loss_price": stop,
        "take_profit_price": 108.0,
        "take_profit_price_2": 112.0,
        "estimated_win_rate": 55,
        "stop_anchor": {
            "source": "signal_bar",
            "bar": "K2",
            "extreme": "low",
            "anchor_price": anchor_price,
            "verified": True,
        },
    }


def test_long_stop_must_be_beyond_anchor_and_noise_floor() -> None:
    errors = validate_order_trade_metrics(_long(97.9), kline_frame=_frame())
    assert any("structural anchor" in error for error in errors)


def test_long_stop_beyond_anchor_and_noise_floor_passes() -> None:
    errors = validate_order_trade_metrics(_long(97.7), kline_frame=_frame())
    assert not errors


def test_hallucinated_anchor_price_is_rejected() -> None:
    errors = validate_order_trade_metrics(_long(97.0, anchor_price=97.5), kline_frame=_frame())
    assert any("anchor price" in error for error in errors)


def test_new_order_without_verifiable_anchor_is_rejected_when_frame_present() -> None:
    decision = _long(97.0)
    decision.pop("stop_anchor")
    errors = validate_order_trade_metrics(decision, kline_frame=_frame())
    assert any("stop_anchor" in error for error in errors)
