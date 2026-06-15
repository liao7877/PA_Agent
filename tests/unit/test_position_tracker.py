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
        placement_ref_high=4298.0,
        placement_ref_low=4277.0,
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


def test_filled_position_adjust_action_without_prices_does_not_notify(store, notifier):
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
    assert not any(m.event.value == "manage" for m in notifier.messages)


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
    cancelled = [m for m in notifier.messages if m.event.value == "order_cancelled"]
    assert cancelled


def test_planned_cancelled_when_ai_uses_close_action(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    pos = tracker.apply_decision(
        symbol="X",
        timeframe="15m",
        decision={
            "decision": {
                "order_type": "不下单",
                "position_action": "平仓",
                "reasoning": "结构失效，撤销挂单。",
            }
        },
    )
    assert pos is None
    assert any(m.event.value == "order_cancelled" for m in notifier.messages)


def test_planned_hold_keeps_order_without_cancel_notify(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    pos = tracker.apply_decision(
        symbol="X",
        timeframe="15m",
        decision={
            "decision": {
                "order_type": "不下单",
                "position_action": "持有",
                "reasoning": "继续等待价格回撤至挂单价。",
            }
        },
    )
    assert pos is not None
    assert pos.status is PositionStatus.PLANNED
    assert tracker.get_active("X", "15m") is not None
    assert not any(m.event.value == "order_cancelled" for m in notifier.messages)


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


def test_planned_entry_and_tp_sl_updated(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    updated = {
        "decision": {
            "order_type": "限价单",
            "order_direction": "做多",
            "entry_price": 101.0,
            "take_profit_price": 112.0,
            "stop_loss_price": 96.0,
        }
    }
    pos = tracker.apply_decision(symbol="X", timeframe="15m", decision=updated)
    assert pos is not None
    assert pos.status is PositionStatus.PLANNED
    assert pos.entry_price == 101.0
    assert pos.take_profit_price == 112.0
    assert pos.stop_loss_price == 96.0
    assert any(m.event.value == "manage" for m in notifier.messages)


def test_planned_reversal_replaces_without_exit_notify(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    short = {
        "decision": {
            "order_type": "突破单",
            "order_direction": "做空",
            "entry_price": 95.0,
            "take_profit_price": 85.0,
            "stop_loss_price": 100.0,
        }
    }
    pos = tracker.apply_decision(symbol="X", timeframe="15m", decision=short)
    assert pos is not None
    assert pos.order_direction == "做空"
    assert pos.order_type == "突破单"
    assert pos.status is PositionStatus.PLANNED
    assert not any(m.event.value == "exit" for m in notifier.messages)


def test_breakout_long_triggers_on_high_break(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    breakout = {
        "decision": {
            "order_type": "突破单",
            "order_direction": "做多",
            "entry_price": 105.0,
            "take_profit_price": 115.0,
            "stop_loss_price": 100.0,
        }
    }
    tracker.apply_decision(
        symbol="X",
        timeframe="15m",
        decision=breakout,
        fill_bar_ts=2_000,
        placement_ref_high=104.0,
        placement_ref_low=100.0,
    )
    # K1 closed bar (before placement bar) already broke 105 — must not retro-fill.
    tracker.on_tick("X", "15m", high=106.0, low=101.0, bar_ts=1_000)
    assert tracker.get_active("X", "15m").status is PositionStatus.PLANNED
    # Placement bar breaks above entry after order was placed.
    tracker.on_tick("X", "15m", high=106.0, low=101.0, bar_ts=2_000)
    assert tracker.get_active("X", "15m").status is PositionStatus.FILLED
    assert any(m.event.value == "entry_filled" for m in notifier.messages)


def test_breakout_not_filled_when_price_already_through_at_placement(store, notifier):
    """Breakout level already traded through on K0 when decision lands — no false fill."""
    tracker = PositionTracker(store=store, notifier=notifier)
    breakout = {
        "decision": {
            "order_type": "突破单",
            "order_direction": "做多",
            "entry_price": 105.0,
            "take_profit_price": 115.0,
            "stop_loss_price": 100.0,
        }
    }
    tracker.apply_decision(
        symbol="X",
        timeframe="15m",
        decision=breakout,
        fill_bar_ts=2_000,
        placement_ref_high=106.0,
        placement_ref_low=100.0,
    )
    pos = tracker.get_active("X", "15m")
    assert pos.status is PositionStatus.PLANNED
    assert pos.entry_missed is True
    tracker.on_tick("X", "15m", high=107.0, low=101.0, bar_ts=2_000)
    tracker.on_tick("X", "15m", high=108.0, low=102.0, bar_ts=3_000)
    assert tracker.get_active("X", "15m").status is PositionStatus.PLANNED
    assert not any(m.event.value == "entry_filled" for m in notifier.messages)


def test_filled_take_profit_on_forming_bar_realtime(store, notifier):
    """TP fires on live K0 update — no need to wait for bar close."""
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    tracker.on_tick("X", "15m", high=100.0, low=100.0, bar_ts=1_000)
    tracker.on_tick("X", "15m", high=110.5, low=105.0, bar_ts=2_000)
    assert tracker.get_active("X", "15m") is None
    exits = [m for m in notifier.messages if m.event.value == "exit"]
    assert exits and "止盈" in exits[-1].text


def test_filled_stop_loss_on_forming_bar_realtime(store, notifier):
    tracker = PositionTracker(store=store, notifier=notifier)
    tracker.apply_decision(symbol="X", timeframe="15m", decision=_long_decision())
    tracker.on_tick("X", "15m", high=100.0, low=100.0, bar_ts=1_000)
    tracker.on_tick("X", "15m", high=98.0, low=94.5, bar_ts=2_000)
    assert tracker.get_active("X", "15m") is None
    exits = [m for m in notifier.messages if m.event.value == "exit"]
    assert exits and "止损" in exits[-1].text


def test_planned_fill_on_forming_bar_realtime_update(store, notifier):
    """Plan order tracks the live forming bar — no need to wait for bar close."""
    tracker = PositionTracker(store=store, notifier=notifier)
    breakout = {
        "decision": {
            "order_type": "突破单",
            "order_direction": "做多",
            "entry_price": 105.0,
            "take_profit_price": 115.0,
            "stop_loss_price": 100.0,
        }
    }
    tracker.apply_decision(
        symbol="X",
        timeframe="15m",
        decision=breakout,
        fill_bar_ts=2_000,
        placement_ref_high=104.0,
        placement_ref_low=100.0,
    )
    tracker.on_tick("X", "15m", high=105.2, low=101.0, bar_ts=2_000)
    assert tracker.get_active("X", "15m").status is PositionStatus.FILLED
    assert any(m.event.value == "entry_filled" for m in notifier.messages)


def test_limit_not_filled_on_k1_touch_before_placement(store, notifier):
    """K1 already dipped to limit price before the pending order existed."""
    tracker = PositionTracker(store=store, notifier=notifier)
    limit = {
        "decision": {
            "order_type": "限价单",
            "order_direction": "做多",
            "entry_price": 100.0,
            "take_profit_price": 110.0,
            "stop_loss_price": 95.0,
        }
    }
    tracker.apply_decision(
        symbol="X",
        timeframe="15m",
        decision=limit,
        fill_bar_ts=2_000,
        placement_ref_high=102.0,
        placement_ref_low=101.0,
    )
    tracker.on_tick("X", "15m", high=101.0, low=99.5, bar_ts=1_000)
    assert tracker.get_active("X", "15m").status is PositionStatus.PLANNED
    assert not any(m.event.value == "entry_filled" for m in notifier.messages)
    tracker.on_tick("X", "15m", high=101.0, low=99.5, bar_ts=2_000)
    assert tracker.get_active("X", "15m").status is PositionStatus.FILLED
