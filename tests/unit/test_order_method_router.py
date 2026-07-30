"""Tests for §11 order-method routing."""
from __future__ import annotations

from pa_agent.ai.decision_nodes import route_order_method


def test_breakout_without_basis_waits_instead_of_falling_back_to_limit() -> None:
    decision = {
        "order_type": "突破单",
        "entry_price": 101.0,
        "stop_loss_price": 99.0,
        "take_profit_price": 102.0,
        "take_profit_price_2": 103.0,
    }
    trace = [{"node_id": "10.3", "answer": "是", "reason": "ok"}]
    stage1 = {"cycle_position": "normal_channel"}
    nodes = route_order_method(stage1, decision, trace, entry_confirmed=True)
    assert decision["order_type"] == "不下单"
    assert decision["entry_price"] is None
    assert decision["stop_loss_price"] is None
    assert decision["take_profit_price"] is None
    assert decision["take_profit_price_2"] is None
    assert nodes == []


def test_model_breakout_preserved_for_broad_channel() -> None:
    decision = {
        "order_type": "突破单",
        "order_direction": "做空",
        "entry_price": 4210.348,
        "entry_basis_bar": "K1",
        "entry_basis_extreme": "low",
        "stop_loss_price": 4228.399,
        "take_profit_price": 4183.278,
        "take_profit_price_2": 4170.0,
    }
    trace = [{"node_id": "10.3", "answer": "是", "reason": "ok"}]
    stage1 = {"cycle_position": "broad_channel"}
    nodes = route_order_method(stage1, decision, trace, entry_confirmed=True)
    assert decision["order_type"] == "突破单"
    assert nodes
    assert nodes[-1].node_id == "11.2"
    assert nodes[-1].answer == "是"


def test_model_limit_order_is_not_preserved_without_confirmed_entry() -> None:
    decision = {
        "order_type": "限价单",
        "entry_price": 100.5,
        "stop_loss_price": 99.0,
        "take_profit_price": 101.5,
        "take_profit_price_2": 102.5,
    }
    trace = [{"node_id": "10.3", "answer": "是", "reason": "ok"}]
    stage1 = {"cycle_position": "normal_channel"}
    nodes = route_order_method(stage1, decision, trace, entry_confirmed=False)
    assert decision["order_type"] == "不下单"
    assert nodes == []


def test_trading_range_middle_rejects_even_confirmed_candidate() -> None:
    decision = {
        "order_type": "突破单",
        "order_direction": "做多",
        "entry_price": 101.0,
        "entry_basis_bar": "K1",
        "entry_basis_extreme": "high",
        "entry_rule": "K1高点上方1跳动",
        "stop_loss_price": 99.0,
        "take_profit_price": 103.0,
        "take_profit_price_2": 105.0,
        "estimated_win_rate": 55,
    }
    trace = [{"node_id": "10.3", "answer": "是", "reason": "ok"}]
    stage1 = {
        "cycle_position": "trading_range",
        "bar_analysis": {"tr_position": "middle"},
        "detected_patterns": ["barbwire"],
    }
    nodes = route_order_method(stage1, decision, trace, setup_confirmed=True)
    assert decision["order_type"] == "不下单"
    assert nodes == []


def test_spike_ending_preserves_confirmed_pending_breakout() -> None:
    decision = {
        "order_type": "突破单",
        "order_direction": "做空",
        "entry_price": 99.0,
        "entry_basis_bar": "K1",
        "entry_basis_extreme": "low",
        "entry_rule": "K1低点下方1跳动",
        "stop_loss_price": 101.0,
        "take_profit_price": 97.0,
        "take_profit_price_2": 95.0,
        "estimated_win_rate": 55,
    }
    trace = [{"node_id": "10.3", "answer": "是", "reason": "ok"}]
    nodes = route_order_method(
        {"cycle_position": "spike", "spike_stage": "pullback"},
        decision,
        trace,
        setup_confirmed=True,
    )
    assert decision["order_type"] == "突破单"
    assert nodes[-1].node_id == "11.2"
