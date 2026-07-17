"""Unit tests for P0/P1 coherence validators."""
from __future__ import annotations

import json

import pytest

from pa_agent.ai.coherence_checks import (
    auto_fix_invalid_bar_labels,
    validate_bar_by_bar_vs_features,
    validate_duplicate_bar_ranges,
    validate_incremental_stage1_coherence,
    validate_stage1_coherence,
    validate_stage2_coherence,
)
from pa_agent.ai.json_validator import Ok
from tests.fixtures.validators import schema_test_validator
from pa_agent.data.base import IndicatorBundle, KlineBar, KlineFrame
from tests.fixtures.gate_trace import make_bar_by_bar_summary, make_mandatory_gate_trace_proceed


def _frame(n: int = 5) -> KlineFrame:
    bars = tuple(
        KlineBar(
            seq=i + 1,
            ts_open=1000 - i * 60_000,
            open=2000.0,
            high=2010.0,
            low=1990.0,
            close=2005.0,
            volume=1.0,
            closed=True,
        )
        for i in range(n)
    )
    return KlineFrame(
        symbol="XAUUSD",
        timeframe="15m",
        bars=bars,
        snapshot_ts_local_ms=1,
        indicators=IndicatorBundle(
            ema20=tuple([2000.0] * n),
            atr14=tuple([10.0] * n),
        ),
    )


def _stage1_proceed() -> dict:
    return {
        "cycle_position": "normal_channel",
        "direction": "bullish",
        "diagnosis_confidence": 70,
        "market_phase": "stable",
        "detected_patterns": [],
        "key_signals": [],
        "htf_context": "x",
        "entry_setup": "x",
        "strategy_files_needed": [],
        "bar_by_bar_summary": make_bar_by_bar_summary(5),
        "gate_trace": make_mandatory_gate_trace_proceed(max_seq=5),
        "gate_result": "proceed",
    }


def test_mandatory_gate_nodes_missing_on_proceed() -> None:
    s1 = _stage1_proceed()
    s1["gate_trace"] = s1["gate_trace"][:3]
    errs = validate_stage1_coherence(s1, kline_frame=_frame())
    assert any("requires gate_trace nodes" in e for e in errs)


def test_stage2_diagnosis_summary_must_match_stage1() -> None:
    s1 = _stage1_proceed()
    s2 = {
        "decision": {"order_type": "不下单", "order_direction": None,
                     "entry_price": None, "take_profit_price": None,
                     "stop_loss_price": None, "reasoning": "x" * 40,
                     "diagnosis_confidence": 1, "diagnosis_confidence_reasoning": "x",
                     "trade_confidence": 1, "trade_confidence_reasoning": "x",
                     "estimated_win_rate": None, "estimated_win_rate_reasoning": "x",
                     "key_factors": [], "watch_points": [], "risk_assessment": "x",
                     "invalidation_condition": "x"},
        "diagnosis_summary": {
            "cycle_position": "trading_range",
            "direction": "bullish",
            "key_signals": [],
        },
        "decision_trace": [
            {"node_id": "10.3", "question": "q", "answer": "否",
             "reason": "r", "bar_range": "K1"},
        ],
        "terminal": {"node_id": "10.3", "outcome": "wait", "label": "x"},
    }
    errs = validate_stage2_coherence(s2, s1, kline_frame=_frame())
    assert any("cycle_position" in e for e in errs)


def test_stage2_order_direction_conflicts_stage1() -> None:
    s1 = _stage1_proceed()
    s2 = {
        "decision": {
            "order_type": "限价单",
            "order_direction": "做空",
            "entry_price": 1.0,
            "take_profit_price": 0.5,
            "stop_loss_price": 1.5,
            "reasoning": "x" * 40,
            "diagnosis_confidence": 1,
            "diagnosis_confidence_reasoning": "x",
            "trade_confidence": 80,
            "trade_confidence_reasoning": "x",
            "estimated_win_rate": 55,
            "estimated_win_rate_reasoning": "x",
            "key_factors": [],
            "watch_points": [],
            "risk_assessment": "x",
            "invalidation_condition": "x",
        },
        "diagnosis_summary": {
            "cycle_position": "normal_channel",
            "direction": "bullish",
            "key_signals": [],
        },
        "decision_trace": [
            {"node_id": "9.1", "question": "q", "answer": "是", "reason": "r", "bar_range": "K2"},
            {"node_id": "10.1", "question": "q", "answer": "是", "reason": "r", "bar_range": "K1"},
            {"node_id": "10.2", "question": "q", "answer": "否", "reason": "r", "bar_range": "K1"},
            {"node_id": "10.3", "question": "q", "answer": "是", "reason": "r", "bar_range": "K1"},
        ],
        "terminal": {"node_id": "11.2", "outcome": "trade", "label": "x"},
        "bar_analysis": {
            "signal_bar": {"bar": "K2", "quality": "strong", "reason": "x"},
            "entry_bar": {"bar": "K1", "strength": "strong", "follow_through": True},
        },
    }
    errs = validate_stage2_coherence(s2, s1, kline_frame=_frame())
    assert any("countertrend" in error or "逆势" in error for error in errs)
    assert not any(
        isinstance(x, dict) and x.get("node_id") == "2.3" and x.get("_auto_injected")
        for x in s2["decision_trace"]
    )


def test_duplicate_single_bar_range_is_allowed() -> None:
    """Multiple §9/§10 nodes may legitimately cite the same signal bar (K1)."""
    trace = [
        {"node_id": "9.0", "answer": "否", "reason": "r", "bar_range": "K1"},
        {"node_id": "9.4", "answer": "不适用", "reason": "r", "bar_range": "K1", "skipped": True},
        {"node_id": "9.6", "answer": "不适用", "reason": "r", "bar_range": "K1", "skipped": True},
        {"node_id": "10.1", "answer": "否", "reason": "r", "bar_range": "K1"},
        {"node_id": "10.2", "answer": "不适用", "reason": "r", "bar_range": "K1", "skipped": True},
        {"node_id": "14", "answer": "否", "reason": "r", "bar_range": "K8-K1"},
    ]
    assert validate_duplicate_bar_ranges(trace, path_prefix="decision_trace", min_items=5) == []


def test_duplicate_multi_bar_range_still_errors() -> None:
    # Narrow windows (fewer than 4 bars) are still flagged when overused.
    trace = [{"node_id": f"9.{i}", "answer": "否", "reason": "r", "bar_range": "K3-K2"} for i in range(6)]
    errs = validate_duplicate_bar_ranges(trace, path_prefix="decision_trace", min_items=5)
    assert any("identical bar_range" in e for e in errs)


def test_incremental_requires_delta_language() -> None:
    s1 = _stage1_proceed()
    errs = validate_incremental_stage1_coherence(s1, new_bar_count=3)
    assert any("incremental_delta" in e for e in errs)
    s1["incremental_delta"] = {
        "new_closed_bars": ["K1", "K2", "K3"],
        "changed_fields": [],
        "summary": "新增K线后结构延续，周期判断不变",
    }
    assert not validate_incremental_stage1_coherence(s1, new_bar_count=3)


def test_validator_accepts_full_stage1_fixture() -> None:
    s1 = _stage1_proceed()
    s1["bar_by_bar_summary"][0]["bar_type"] = "inside"
    result = schema_test_validator().validate(
        "stage1", json.dumps(s1, ensure_ascii=False), kline_frame=_frame()
    )
    assert isinstance(result, Ok)


def test_bar_type_mismatch_near_threshold_does_not_error_in_strict() -> None:
    """Near hard cutoffs (doji/trend thresholds), strict mode should not over-error."""
    # Build a bar with body_ratio ~= 0.25 (doji cutoff).
    # Range=10, body=2.6 -> 0.26 (within eps 0.02).
    frame = KlineFrame(
        symbol="XAUUSD",
        timeframe="15m",
        bars=(
            KlineBar(
                seq=1,
                ts_open=1,
                open=100.0,
                high=110.0,
                low=100.0,
                close=102.6,
                volume=1.0,
                closed=True,
            ),
        ),
        snapshot_ts_local_ms=1,
        indicators=IndicatorBundle(ema20=(100.0,), atr14=(10.0,)),
    )
    stage1 = {
        "bar_by_bar_summary": [{"bar": "K1", "bar_type": "trend_bull", "reason": "x"}]
    }
    # Program would likely classify as doji (body_ratio <= 0.25) or other; we tolerate mismatch.
    errs = validate_bar_by_bar_vs_features(stage1, kline_frame=frame, strict=True)
    assert errs == []


def test_duplicate_bar_range_wide_window_allowed() -> None:
    trace = [
        {"node_id": f"9.{i}", "answer": "是", "bar_range": "K8-K1", "reason": "x"}
        for i in range(5)
    ]
    assert validate_duplicate_bar_ranges(trace, path_prefix="decision_trace", min_items=5) == []


def test_auto_fix_k0_bar_label_to_k1() -> None:
    frame = _frame(5)
    stage1 = {
        "bar_by_bar_summary": [
            {"bar": "K0", "bar_type": "doji", "reason": "model slip"},
        ]
    }
    msgs = auto_fix_invalid_bar_labels(stage1, kline_frame=frame)
    assert msgs == ["bar_by_bar_summary[0].bar K0 -> K1"]
    assert stage1["bar_by_bar_summary"][0]["bar"] == "K1"
    errs = validate_bar_by_bar_vs_features(stage1, kline_frame=frame, strict=True)
    assert errs == []


def test_opposite_trend_direction_still_errors_in_strict() -> None:
    frame = KlineFrame(
        symbol="XAUUSD",
        timeframe="15m",
        bars=(
            # K1 inside K2
            KlineBar(
                seq=1,
                ts_open=2,
                open=105.0,
                high=109.0,
                low=101.0,
                close=106.0,
                volume=1.0,
                closed=True,
            ),
            KlineBar(
                seq=2,
                ts_open=1,
                open=100.0,
                high=110.0,
                low=100.0,
                close=109.0,
                volume=1.0,
                closed=True,
            ),
        ),
        snapshot_ts_local_ms=1,
        indicators=IndicatorBundle(ema20=(100.0, 100.0), atr14=(10.0, 10.0)),
    )
    stage1 = {
        "bar_by_bar_summary": [{"bar": "K2", "bar_type": "trend_bear", "reason": "x"}]
    }
    errs = validate_bar_by_bar_vs_features(stage1, kline_frame=frame, strict=True)
    assert any("contradicts" in e for e in errs)
