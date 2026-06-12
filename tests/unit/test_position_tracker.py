"""Unit tests for position tracking (store + tracker fill/exit/manage)."""
from __future__ import annotations

import pytest

from pa_agent.positions.model import PositionState, PositionStatus
from pa_agent.positions.store import PositionStore
from pa_agent.positions.tracker import PositionTracker


class _RecordingNotifier:
    def __init__(self):
        self.messages = []

    def notify(self, message):
        self.messages.append(message)


@pytest.fixture()
def store(tmp_path):
    return PositionStore(path=tmp_path / "positions.json")


@pytest.fixture()
def notifier():
    return _RecordingNotifier()


def _long_decision():
    return {
        "decision": {
            "order_type": "限价单",
            "order_direction": "做多",
            "entry_price": 100.0,
            "take_profit_price": 110.0,
            "stop_loss_price": 95.0,
        }
    }


# ── Store ──────────────────────────────────────────────────────────────────────
def test_store_upsert_and_get(store):
    pos = PositionState(
        symbol="X", timeframe="15m", order_direction="做多",
        order_type="限价单", entry_price=100.0,
    )
    store.upsert_active(pos)
    got = store.get_active("X", "15m")
    assert got is not None
    assert got.entry_price == 100.0


def test_store_persists_across_instances(tmp_path):
    p = tmp_path / "positions.json"
    s1 = PositionStore(path=p)
    s1.upsert_active(PositionState(
        symbol="X", timeframe="15m", order_direction="做空",
        order_type="限价单", entry_price=50.0,
    ))
    s2 = PositionStore(path=p)
    assert s2.get_active("X", "15m") is not None


def test_store_close_moves_to_history(store):
    pos = PositionState(
        symbol="X", timeframe="15m", order_direction="做多",
        order_type="限价单", entry_price=100.0, status=PositionStatus.FILLED,
    )
    store.upsert_active(pos)
    store.close_active(pos)
    assert store.get_active("X", "15m") is None


# ── Tracker: open ───────────────────────────────────────────────────────────────
def test_apply_decision_opens_planned(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    pos = tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    assert pos is not None
    assert pos.status is PositionStatus.PLANNED
    assert pos.entry_price == 100.0


def test_apply_decision_no_trade_no_position(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    pos = tracker.apply_decision(
        symbol="X", timeframe="15m",
        decision={"decision": {"order_type": "不下单"}},
    )
    assert pos is None


def test_market_order_fills_immediately(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    pos = tracker.apply_decision(
        symbol="X", timeframe="15m",
        decision={"decision": {"order_type": "市价单", "order_direction": "做多",
                               "entry_price": 100.0, "take_profit_price": 110.0,
                               "stop_loss_price": 95.0}},
    )
    assert pos.status is PositionStatus.FILLED


# ── Tracker: fill detection ─────────────────────────────────────────────────────
def test_tick_fills_planned_on_touch(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    # Price has not reached 100 yet
    tracker.on_tick("X", "15m", high=99.0, low=98.0)
    assert tracker.get_active("X", "15m").status is PositionStatus.PLANNED
    # Price dips to touch 100
    tracker.on_tick("X", "15m", high=101.0, low=99.5)
    pos = tracker.get_active("X", "15m")
    assert pos.status is PositionStatus.FILLED
    assert any(m.event.value == "entry_filled" for m in notifier.messages)


def test_tick_exit_take_profit_long(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    tracker.on_tick("X", "15m", high=100.0, low=100.0)   # fill
    tracker.on_tick("X", "15m", high=111.0, low=108.0)   # touch TP=110
    assert tracker.get_active("X", "15m") is None
    assert any(m.event.value == "exit" for m in notifier.messages)


def test_tick_exit_stop_loss_long(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    tracker.on_tick("X", "15m", high=100.0, low=100.0)   # fill
    tracker.on_tick("X", "15m", high=98.0, low=94.0)     # touch SL=95
    assert tracker.get_active("X", "15m") is None
    exits = [m for m in notifier.messages if m.event.value == "exit"]
    assert exits and "止损" in exits[-1].text


def test_market_short_not_stopped_on_entry_bar_same_bar(store, notifier):
    """SCS market short: SL above signal high must not fire on the entry bar itself."""
    tracker = PositionTracker(store=store, notifier=notifier)
    entry_ts = 1_700_000_000_000
    tracker.apply_decision(
        symbol="X",
        timeframe="15m",
        fill_bar_ts=entry_ts,
        decision={
            "decision": {
                "order_type": "市价单",
                "order_direction": "做空",
                "entry_price": 4278.76,
                "take_profit_price": 4235.0,
                "stop_loss_price": 4297.02,
            }
        },
    )
    pos = tracker.get_active("X", "15m")
    assert pos is not None and pos.status is PositionStatus.FILLED
    tracker.on_tick("X", "15m", high=4298.0, low=4277.0, bar_ts=entry_ts)
    assert tracker.get_active("X", "15m") is not None


def test_short_position_stop_and_target(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    short = {"decision": {"order_type": "限价单", "order_direction": "做空",
                          "entry_price": 100.0, "take_profit_price": 90.0,
                          "stop_loss_price": 105.0}}
    tracker.apply_decision(symbol="X", timeframe="15m", decision=short)
    tracker.on_tick("X", "15m", high=100.0, low=100.0)   # fill
    tracker.on_tick("X", "15m", high=89.0, low=88.0)     # touch TP=90 (price below)
    assert tracker.get_active("X", "15m") is None


# ── Tracker: management via new decision ────────────────────────────────────────
def test_filled_position_manage_adjusts_sl(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    tracker.on_tick("X", "15m", high=100.0, low=100.0)   # fill
    # New decision keeps same direction but moves SL up to 98
    manage = {"decision": {"order_type": "限价单", "order_direction": "做多",
                           "entry_price": 100.0, "take_profit_price": 110.0,
                           "stop_loss_price": 98.0}}
    pos = tracker.apply_decision(symbol="X", timeframe="15m", decision=manage)
    assert pos.stop_loss_price == 98.0
    assert any(m.event.value == "manage" for m in notifier.messages)


def test_filled_position_ai_close(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    tracker.on_tick("X", "15m", high=100.0, low=100.0)   # fill
    pos = tracker.apply_decision(
        symbol="X", timeframe="15m",
        decision={
            "decision": {
                "order_type": "不下单",
                "position_action": "平仓",
                "reasoning": "结构走弱，建议提前出场观望。",
            }
        },
        current_price=105.5,
    )
    assert pos is None
    assert tracker.get_active("X", "15m") is None
    exits = [m for m in notifier.messages if m.event.value == "exit"]
    assert exits
    assert "105.5" in exits[-1].text


def test_filled_position_adjust_action_updates_sl_and_notifies(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    tracker.on_tick("X", "15m", high=100.0, low=100.0)   # fill
    pos = tracker.apply_decision(
        symbol="X", timeframe="15m",
        decision={
            "decision": {
                "order_type": "不下单",
                "position_action": "调整",
                "order_direction": "做多",
                "take_profit_price": 110.0,
                "stop_loss_price": 98.0,
                "reasoning": "上移止损保护利润。",
            }
        },
    )
    assert pos is not None
    assert pos.stop_loss_price == 98.0
    managed = [m for m in notifier.messages if m.event.value == "manage"]
    assert managed
    assert "98" in managed[-1].text
    assert not any(m.event.value == "exit" for m in notifier.messages)


def test_filled_position_adjust_action_without_prices_notifies_advisory(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    tracker.on_tick("X", "15m", high=100.0, low=100.0)   # fill
    pos = tracker.apply_decision(
        symbol="X", timeframe="15m",
        decision={
            "decision": {
                "order_type": "不下单",
                "position_action": "调整",
                "position_advice": "下一根若跌破 K1 低点，将止损下移至 97。",
            }
        },
    )
    assert pos is not None
    managed = [m for m in notifier.messages if m.event.value == "manage"]
    assert managed
    assert "97" in managed[-1].text


def test_filled_position_no_trade_without_close_phrase_does_not_exit(store, notifier):
    """Bare 不下单 on a filled position must not trigger a false exit notify."""
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    tracker.on_tick("X", "15m", high=100.0, low=100.0)   # fill
    pos = tracker.apply_decision(
        symbol="X", timeframe="15m",
        decision={
            "decision": {
                "order_type": "不下单",
                "reasoning": "继续持有，等待下一根确认。",
            }
        },
    )
    assert pos is not None
    assert pos.status is PositionStatus.FILLED
    assert not any(m.event.value == "exit" for m in notifier.messages)


def test_planned_cancelled_by_no_trade(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    pos = tracker.apply_decision(
        symbol="X", timeframe="15m",
        decision={"decision": {"order_type": "不下单"}},
    )
    assert pos is None
    assert tracker.get_active("X", "15m") is None


def test_reversal_closes_and_opens_opposite(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    tracker.on_tick("X", "15m", high=100.0, low=100.0)   # fill long
    short = {"decision": {"order_type": "限价单", "order_direction": "做空",
                          "entry_price": 105.0, "take_profit_price": 95.0,
                          "stop_loss_price": 110.0}}
    pos = tracker.apply_decision(symbol="X", timeframe="15m", decision=short)
    assert pos is not None
    assert pos.order_direction == "做空"
    assert pos.status is PositionStatus.PLANNED
    assert any(m.event.value == "exit" for m in notifier.messages)
