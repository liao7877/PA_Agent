"""Unit tests for structured position_action fields."""
from __future__ import annotations

from pa_agent.positions.decision_fields import (
    is_position_adjust,
    is_position_close,
    position_advice_text,
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


def test_position_advice_prefers_structured_field():
    inner = {
        "position_action": "调整",
        "position_advice": "将止损上移至 4335。",
        "reasoning": "很长的分析理由……",
    }
    assert position_advice_text(inner) == "将止损上移至 4335。"
