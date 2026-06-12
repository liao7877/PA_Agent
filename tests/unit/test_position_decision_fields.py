"""Unit tests for structured position_action fields."""
from __future__ import annotations

from pa_agent.positions.decision_fields import (
    is_actionable_trade_decision,
    is_position_adjust,
    is_position_close,
    position_advice_text,
    should_apply_position_despite_validation,
)


def test_position_action_adjust():
    inner = {
        "order_type": "不下单",
        "position_action": "调整",
        "order_direction": "做多",
        "stop_loss_price": 4335.0,
        "reasoning": "上移止损保护利润。",
    }
    assert is_position_adjust(inner)
    assert not is_position_close(inner)


def test_position_action_close():
    inner = {"order_type": "不下单", "position_action": "平仓", "reasoning": "动能衰竭。"}
    assert is_position_close(inner)
    assert not is_position_adjust(inner)


def test_actionable_trade_decision_requires_prices_and_direction():
    root = {
        "decision": {
            "order_type": "市价单",
            "order_direction": "做空",
            "entry_price": 100.0,
            "take_profit_price": 90.0,
            "stop_loss_price": 105.0,
        }
    }
    assert is_actionable_trade_decision(root)
    assert not is_actionable_trade_decision({"decision": {"order_type": "不下单"}})


def test_format_only_validation_allows_position_apply():
    exc = {
        "type": "validation_error",
        "stage": "stage2",
        "category": "c",
        "invalid_fields": ["signal_chain:market order requires a concrete entry_bar.bar"],
        "decision_preserved": True,
    }
    decision = {
        "decision": {
            "order_type": "市价单",
            "order_direction": "做空",
            "entry_price": 4278.76,
            "take_profit_price": 4235.0,
            "stop_loss_price": 4297.02,
        }
    }
    assert should_apply_position_despite_validation(exc, stage2_decision=decision)


def test_metrics_validation_blocks_position_apply():
    exc = {
        "type": "validation_error",
        "stage": "stage2",
        "category": "c",
        "invalid_fields": ["metrics:盈亏比不达标"],
        "decision_preserved": True,
    }
    decision = {
        "decision": {
            "order_type": "突破单",
            "order_direction": "做多",
            "entry_price": 100.0,
            "take_profit_price": 101.0,
            "stop_loss_price": 99.0,
        }
    }
    assert not should_apply_position_despite_validation(exc, stage2_decision=decision)


def test_position_advice_prefers_structured_field():
    inner = {
        "position_action": "调整",
        "position_advice": "将止损上移至 4335。",
        "reasoning": "很长的分析理由……",
    }
    assert position_advice_text(inner) == "将止损上移至 4335。"
