from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from pa_agent.positions.model import PositionState, PositionStatus
from pa_agent.trading_agent.record_handlers import check_position_on_tick


def test_check_position_on_tick_uses_explicit_runtime_identity():
    tracker = MagicMock()
    tracker.get_active.return_value = PositionState(
        symbol="XAUUSD",
        timeframe="15m",
        order_direction="做多",
        order_type="限价单",
        entry_price=100.0,
        status=PositionStatus.FILLED,
    )
    window = SimpleNamespace(
        _ctx=SimpleNamespace(position_tracker=tracker),
        _demo_mode=False,
        _chart_widget=None,
        _symbol_combo=MagicMock(),
        _tf_combo=MagicMock(),
    )
    bar = {
        "high": 111.0,
        "low": 99.0,
        "close": 110.0,
        "ts_open": 1_700_000_000_000,
    }

    check_position_on_tick(
        window,
        [bar],
        symbol="XAUUSD",
        timeframe="15m",
        sync_chart=False,
    )

    tracker.get_active.assert_called_once_with("XAUUSD", "15m")
    tracker.on_live_price.assert_called_once()
    assert tracker.on_live_price.call_args.args[:2] == ("XAUUSD", "15m")
