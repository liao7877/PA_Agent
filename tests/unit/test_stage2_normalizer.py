"""Unit tests for Stage 2 normalizer — next_bar_prediction (T4)."""
from __future__ import annotations

import copy
import json

from pa_agent.ai.json_validator import Ok
from pa_agent.ai.stage2_normalizer import (
    normalize_stage2,
    _normalize_next_bar_prediction,
    _normalize_next_cycle_prediction,
    _normalize_watch_points,
)
from tests.integration.conftest import VALID_STAGE2
from pa_agent.data.base import IndicatorBundle, KlineBar, KlineFrame
from tests.fixtures.validators import schema_test_validator


# ── _normalize_next_bar_prediction direct tests ──────────────────────────────


def test_normalize_next_bar_prediction_unpredictable_forces_null():
    """unpredictable=true → direction/probabilities normalized to None."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 60, "bearish": 30, "neutral": 10},
        "reasoning": "test",
        "unpredictable": True,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["unpredictable"] is True
    assert pred["direction"] is None
    assert pred["probabilities"] is None


def test_normalize_next_bar_prediction_rounds_probabilities():
    """Float probabilities must be rounded to ints, clamped to [0, 100]."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 49.7, "bearish": 30.3, "neutral": 20.0},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    probs = pred["probabilities"]
    assert probs == {"bullish": 50, "bearish": 30, "neutral": 20}


def test_normalize_next_bar_prediction_direction_argmax():
    """direction must be corrected to argmax of probabilities."""
    pred = {
        "direction": "bearish",  # wrong
        "probabilities": {"bullish": 55, "bearish": 35, "neutral": 10},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["direction"] == "bullish"


def test_normalize_next_bar_prediction_direction_argmax_tie_break():
    """Tied probabilities: break by literal order (bullish > bearish > neutral)."""
    pred = {
        "direction": "neutral",
        "probabilities": {"bullish": 40, "bearish": 40, "neutral": 20},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["direction"] == "bullish"  # bullish before bearish


def test_normalize_next_bar_prediction_features_used_dedup_min():
    """features_used must be deduplicated and contain at least stage1_diagnosis."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 70, "bearish": 20, "neutral": 10},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["kline_features", "kline_features", "stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["features_used"] == ["kline_features", "stage1_diagnosis"]


def test_normalize_next_bar_prediction_features_used_min_set():
    """Missing stage1_diagnosis gets prepended."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 70, "bearish": 20, "neutral": 10},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["kline_features"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["features_used"][0] == "stage1_diagnosis"


def test_normalize_next_bar_prediction_reasoning_truncation():
    """Reasoning > 1500 chars gets truncated with ellipsis."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 70, "bearish": 20, "neutral": 10},
        "reasoning": "x" * 2000,
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert len(pred["reasoning"]) == 1500
    assert pred["reasoning"].endswith("…")


def test_normalize_next_bar_prediction_non_string_reasoning():
    """Non-string reasoning becomes empty string."""
    pred = {
        "direction": "bullish",
        "probabilities": {"bullish": 70, "bearish": 20, "neutral": 10},
        "reasoning": 42,
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    assert pred["reasoning"] == ""


def test_normalize_next_bar_prediction_idempotent():
    """Calling normalize twice must produce same result."""
    pred = {
        "direction": "bearish",
        "probabilities": {"bullish": 55, "bearish": 35, "neutral": 10},
        "reasoning": "test reasoning for idempotency check",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(pred)
    first = {**pred}
    _normalize_next_bar_prediction(pred)
    assert pred == first


# ── Integration: normalize_stage2 with prediction ────────────────────────────


def test_normalize_stage2_with_prediction():
    """normalize_stage2 must call _normalize_next_bar_prediction."""
    obj = {
        "decision": {
            "order_type": "不下单",
            "order_direction": None,
            "entry_price": None,
            "take_profit_price": None,
            "stop_loss_price": None,
            "reasoning": "test",
            "diagnosis_confidence": 40,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 30,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": 55,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "diagnosis_summary": {
            "cycle_position": "normal_channel",
            "direction": "bullish",
            "key_signals": [],
        },
        "decision_trace": [
            {"node_id": "10.3", "question": "q", "answer": "否", "reason": "r", "bar_range": "K1"},
        ],
        "terminal": {"node_id": "10.3", "outcome": "wait", "label": "test"},
        "next_bar_prediction": {
            "direction": "bearish",  # wrong: argmax is bullish
            "probabilities": {"bullish": 55.4, "bearish": 34.6, "neutral": 10.0},
            "reasoning": "test",
            "unpredictable": False,
            "features_used": [],
        },
    }
    result = normalize_stage2(obj)
    pred = result["next_bar_prediction"]
    assert pred["direction"] == "bullish"
    assert pred["probabilities"] == {"bullish": 55, "bearish": 35, "neutral": 10}
    assert pred["features_used"] == ["stage1_diagnosis"]


def test_coerce_no_order_when_metrics_fail_after_breakout_entry_snap() -> None:
    """Regression: wrong breakout entry snapped → RR/equation fail → 不下单."""
    frame = KlineFrame(
        symbol="XAUUSD",
        timeframe="1h",
        bars=(
            KlineBar(
                seq=1,
                ts_open=1.0,
                open=10.80,
                high=10.83,
                low=10.66,
                close=10.72,
                volume=1,
                closed=True,
            ),
            KlineBar(
                seq=2,
                ts_open=0.0,
                open=10.71,
                high=10.71,
                low=10.67,
                close=10.68,
                volume=1,
                closed=True,
            ),
        ),
        indicators=IndicatorBundle(ema20=(10.86, 10.86), atr14=(0.08, 0.08)),
        snapshot_ts_local_ms=1,
    )
    payload = {
        "decision": {
            "order_direction": "做空",
            "order_type": "突破单",
            "entry_price": 10.72,
            "entry_basis_bar": "K2",
            "entry_basis_extreme": "low",
            "entry_rule": "K2 low - 1 tick",
            "take_profit_price": 10.50,
            "stop_loss_price": 10.84,
            "reasoning": "test",
            "diagnosis_confidence": 72,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 65,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": 50,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "diagnosis_summary": {
            "cycle_position": "broad_channel",
            "direction": "bearish",
            "key_signals": [],
        },
        "decision_trace": [
            {
                "node_id": "10.3",
                "question": "交易者方程是否通过？",
                "answer": "是",
                "reason": "用10.72/10.84/10.50算RR约1.8",
                "bar_range": "K2-K1",
            },
            {
                "node_id": "11.2",
                "question": "通道回撤？",
                "answer": "是",
                "reason": "test",
                "bar_range": "K2-K1",
            },
        ],
        "terminal": {"node_id": "11.2", "outcome": "trade", "label": "突破做空"},
    }
    out = normalize_stage2(
        payload,
        kline_frame=frame,
        decision_stance="extreme_aggressive",
    )
    assert out["decision"]["order_type"] == "不下单"
    assert out["decision"]["entry_price"] is None
    # Node 10.3 should have answer=否 (now may not be first after §9 node injection)
    trace_103 = next((n for n in out["decision_trace"] if n.get("node_id") == "10.3"), None)
    assert trace_103 is not None, "node 10.3 should be in decision_trace"
    assert trace_103["answer"] == "否"
    assert out["terminal"]["node_id"] == "10.3"
    assert out["terminal"]["outcome"] == "reject"

    result = schema_test_validator().validate(
        "stage2",
        json.dumps(out, ensure_ascii=False),
        decision_stance="extreme_aggressive",
        kline_frame=frame,
    )
    assert isinstance(result, Ok)


def test_coerce_decision_when_103_no_but_prices_remain() -> None:
    """Regression: model says 10.3=否 / terminal=reject but leaves 突破单 prices."""
    payload = {
        "decision": {
            "order_direction": "做多",
            "order_type": "突破单",
            "entry_price": 10.88,
            "entry_basis_bar": "K1",
            "entry_basis_extreme": "high",
            "entry_rule": "K1 高点上方 1 跳动",
            "take_profit_price": 10.94,
            "stop_loss_price": 10.81,
            "reasoning": "方程不通过但仍写突破单",
            "diagnosis_confidence": 58,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 30,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": 45,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "diagnosis_summary": {
            "cycle_position": "trading_range",
            "direction": "neutral",
            "key_signals": [],
        },
        "decision_trace": [
            {
                "node_id": "10.3",
                "question": "交易者方程是否通过？",
                "answer": "否",
                "reason": "RR 0.86:1，45% 胜率方程不通过",
                "bar_range": "K1",
            },
            {
                "node_id": "14.0",
                "question": "是否违反禁止行为清单？",
                "answer": "是",
                "reason": "方程不通过仍强行交易",
                "bar_range": "不适用",
            },
        ],
        "terminal": {
            "node_id": "14.0",
            "outcome": "reject",
            "label": "禁止行为",
        },
    }
    out = normalize_stage2(payload)
    d = out["decision"]
    assert d["order_type"] == "不下单"
    assert d["entry_price"] is None
    assert d["estimated_win_rate"] is None
    assert out["terminal"]["node_id"] == "10.3"

    result = schema_test_validator().validate("stage2", json.dumps(out, ensure_ascii=False))
    assert isinstance(result, Ok)


def test_grounds_market_order_pending_entry_bar() -> None:
    obj = {
        "decision": {
            "order_type": "市价单",
            "order_direction": "做空",
            "entry_price": 4278.76,
            "take_profit_price": 4235.0,
            "stop_loss_price": 4297.02,
            "reasoning": "t",
            "diagnosis_confidence": 80,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 49,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": 45,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "bar_analysis": {
            "last_closed_bar": "K1",
            "signal_bar": {"bar": "K1", "quality": "strong", "pattern": "none", "reason": "t"},
            "entry_bar": {
                "strength": "not_triggered",
                "follow_through": False,
                "still_valid": True,
                "freshness": "pending",
            },
        },
        "diagnosis_summary": {
            "cycle_position": "spike",
            "direction": "bearish",
            "key_signals": [],
        },
        "decision_trace": [],
        "terminal": {"node_id": "14", "outcome": "trade", "label": "t"},
    }
    out = normalize_stage2(obj)
    assert out["bar_analysis"]["entry_bar"]["bar"] == "K1"
    assert out["bar_analysis"]["entry_bar"]["strength"] == "strong"
    assert out["bar_analysis"]["entry_bar"]["freshness"] == "fresh"
    assert out["bar_analysis"]["signal_bar"]["bar"] == "K2"


def test_signal_bar_bumped_when_same_seq_as_entry() -> None:
    obj = {
        "decision": {
            "order_type": "突破单",
            "order_direction": "做空",
            "entry_price": 3.42,
            "entry_basis_bar": "K3",
            "entry_basis_extreme": "low",
            "entry_rule": "test",
            "take_profit_price": 3.0,
            "stop_loss_price": 3.6,
            "reasoning": "t",
            "diagnosis_confidence": 50,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 50,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": 50,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "bar_analysis": {
            "signal_bar": {"bar": "K1", "quality": "valid", "pattern": "bear_reversal"},
            "entry_bar": {
                "bar": "K1",
                "strength": "strong",
                "freshness": "fresh",
                "follow_through": "good",
            },
        },
        "diagnosis_summary": {
            "cycle_position": "trading_range",
            "direction": "bearish",
            "key_signals": [],
        },
        "decision_trace": [],
        "terminal": {"node_id": "0", "outcome": "trade", "label": "t"},
    }
    out = normalize_stage2(obj)
    assert out["bar_analysis"]["signal_bar"]["bar"] == "K2"


def test_normalize_stage2_without_prediction_noop():
    """Legacy Stage 2 without prediction must normalize without error."""
    obj = {
        "decision": {
            "order_type": "不下单",
            "order_direction": None,
            "entry_price": None,
            "take_profit_price": None,
            "stop_loss_price": None,
            "reasoning": "test",
            "diagnosis_confidence": 40,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 30,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": None,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "diagnosis_summary": {
            "cycle_position": "normal_channel",
            "direction": "bullish",
            "key_signals": [],
        },
        "decision_trace": [],
        "terminal": {"node_id": "0", "outcome": "wait", "label": "test"},
    }
    result = normalize_stage2(obj)
    assert "next_bar_prediction" not in result


def test_hoist_probability_alias_for_next_predictions() -> None:
    bar_pred = {
        "direction": "bearish",
        "probability": {"bullish": 30, "bearish": 45, "neutral": 25},
        "reasoning": "x",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_bar_prediction(bar_pred)
    assert bar_pred["probabilities"] == {"bullish": 30, "bearish": 45, "neutral": 25}
    assert "probability" not in bar_pred

    cycle_pred = {
        "cycle": "broad_channel",
        "direction": "neutral",
        "probability": {
            "spike": 2,
            "micro_channel": 5,
            "tight_channel": 10,
            "normal_channel": 20,
            "broad_channel": 35,
            "trending_tr": 18,
            "trading_range": 8,
            "extreme_tr": 2,
        },
        "reasoning": "x",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    _normalize_next_cycle_prediction(cycle_pred)
    assert cycle_pred["probabilities"]["broad_channel"] == 35
    assert "probability" not in cycle_pred


def test_normalize_watch_points_objects_to_strings() -> None:
    decision = {
        "watch_points": [
            {
                "trigger": "价格回撤至4337-4340",
                "action": "等待高质量做多信号棒",
            },
            "已有字符串项",
        ]
    }
    _normalize_watch_points(decision)
    assert decision["watch_points"][0].startswith("价格回撤至4337-4340")
    assert decision["watch_points"][1] == "已有字符串项"

    obj = copy.deepcopy(VALID_STAGE2)
    obj["decision"]["watch_points"] = [
        {"trigger": "跌破支撑", "action": "观察反弹力度"},
    ]
    out = normalize_stage2(obj)
    assert all(isinstance(x, str) for x in out["decision"]["watch_points"])
    result = schema_test_validator().validate(
        "stage2", json.dumps(out, ensure_ascii=False)
    )
    assert isinstance(result, Ok), result


def test_infers_order_direction_from_always_in() -> None:
    obj = {
        "decision": {
            "order_type": "市价单",
            "order_direction": None,
            "entry_price": 100.0,
            "take_profit_price": 90.0,
            "stop_loss_price": 105.0,
            "reasoning": "t",
            "diagnosis_confidence": 70,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 60,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": 55,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "bar_analysis": {
            "always_in": "short",
            "signal_bar": {"bar": "K2", "quality": "strong", "pattern": "none", "reason": "t"},
            "entry_bar": {
                "bar": "K1",
                "strength": "strong",
                "freshness": "fresh",
                "follow_through": "yes",
            },
        },
        "diagnosis_summary": {
            "cycle_position": "broad_channel",
            "direction": "neutral",
            "key_signals": [],
        },
        "decision_trace": [],
        "terminal": {"node_id": "0", "outcome": "trade", "label": "t"},
    }
    out = normalize_stage2(obj)
    assert out["decision"]["order_direction"] == "做空"


def test_infers_order_direction_from_diagnosis_summary() -> None:
    obj = {
        "decision": {
            "order_type": "突破单",
            "order_direction": None,
            "entry_price": 100.0,
            "entry_basis_bar": "K2",
            "entry_basis_extreme": "high",
            "entry_rule": "test",
            "take_profit_price": 110.0,
            "stop_loss_price": 95.0,
            "reasoning": "t",
            "diagnosis_confidence": 70,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 60,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": 55,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "diagnosis_summary": {
            "cycle_position": "normal_channel",
            "direction": "bullish",
            "key_signals": [],
        },
        "bar_analysis": {
            "signal_bar": {"bar": "K2", "quality": "strong", "pattern": "none", "reason": "t"},
            "entry_bar": {
                "bar": None,
                "strength": "not_triggered",
                "freshness": "pending",
                "follow_through": "pending",
            },
        },
        "decision_trace": [],
        "terminal": {"node_id": "0", "outcome": "trade", "label": "t"},
    }
    out = normalize_stage2(obj)
    assert out["decision"]["order_direction"] == "做多"


def test_grounds_market_order_with_stale_freshness() -> None:
    obj = {
        "decision": {
            "order_type": "市价单",
            "order_direction": "做空",
            "entry_price": 4278.76,
            "take_profit_price": 4235.0,
            "stop_loss_price": 4297.02,
            "reasoning": "t",
            "diagnosis_confidence": 80,
            "diagnosis_confidence_reasoning": "t",
            "trade_confidence": 49,
            "trade_confidence_reasoning": "t",
            "estimated_win_rate": 45,
            "estimated_win_rate_reasoning": "t",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "t",
            "invalidation_condition": "t",
        },
        "bar_analysis": {
            "last_closed_bar": "K1",
            "signal_bar": {"bar": "K2", "quality": "strong", "pattern": "none", "reason": "t"},
            "entry_bar": {
                "bar": None,
                "strength": "strong",
                "follow_through": "pending",
                "freshness": "stale",
            },
        },
        "diagnosis_summary": {
            "cycle_position": "spike",
            "direction": "bearish",
            "key_signals": [],
        },
        "decision_trace": [],
        "terminal": {"node_id": "14", "outcome": "trade", "label": "t"},
    }
    out = normalize_stage2(obj)
    entry = out["bar_analysis"]["entry_bar"]
    assert entry["bar"] == "K1"
    assert entry["freshness"] == "fresh"


def test_normalize_preserves_position_adjust_tp_sl_on_no_order() -> None:
    obj = copy.deepcopy(VALID_STAGE2)
    obj["decision"].update(
        {
            "order_type": "不下单",
            "position_action": "调整",
            "order_direction": "做多",
            "entry_price": 4340.0,
            "take_profit_price": 4380.0,
            "stop_loss_price": 4335.0,
            "estimated_win_rate": 55,
        }
    )
    out = normalize_stage2(obj)
    decision = out["decision"]
    assert decision["order_type"] == "不下单"
    assert decision["position_action"] == "调整"
    assert decision["take_profit_price"] == 4380.0
    assert decision["stop_loss_price"] == 4335.0
    assert decision["order_direction"] == "做多"
    assert decision["entry_price"] is None
    assert decision["estimated_win_rate"] is None
