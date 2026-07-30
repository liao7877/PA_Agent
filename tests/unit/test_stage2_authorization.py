"""Regression tests for deterministic Stage-2 entry authorization."""
from __future__ import annotations

from pa_agent.ai.decision_nodes import DecisionNodeEngine, judge_signal_bar_closed
from pa_agent.ai.stage2_normalizer import normalize_stage2
from pa_agent.data.base import IndicatorBundle, KlineBar, KlineFrame


def _frame(*, signal_type: str = "bear", signal_closed: bool = True) -> KlineFrame:
    bars: list[KlineBar] = []
    for seq in range(1, 26):
        if seq == 2:
            if signal_type == "bear":
                open_, close, high, low = 105.0, 101.0, 106.0, 100.0
            else:
                open_, close, high, low = 101.0, 105.0, 106.0, 100.0
            closed = signal_closed
        else:
            open_, close, high, low = 100.0, 101.0, 102.0, 99.0
            closed = True
        bars.append(
            KlineBar(
                seq=seq,
                ts_open=1_700_000_000_000 - seq * 900_000,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=100,
                closed=closed,
            )
        )
    return KlineFrame(
        symbol="TEST",
        timeframe="15m",
        bars=tuple(bars),
        indicators=IndicatorBundle(
            ema20=tuple(100.0 for _ in bars),
            atr14=tuple(5.0 for _ in bars),
        ),
        snapshot_ts_local_ms=1_700_000_000_000,
    )


def _stage2_long_breakout() -> dict:
    return {
        "bar_analysis": {
            "signal_bar": {"bar": "K2", "quality": "medium", "reason": "claimed long"},
            "entry_bar": {
                "bar": None,
                "strength": "not_triggered",
                "freshness": "pending",
                "follow_through": "pending",
            },
        },
        "decision": {
            "order_type": "突破单",
            "order_direction": "做多",
            "entry_price": 106.1,
            "entry_basis_bar": "K2",
            "entry_basis_extreme": "high",
            "entry_rule": "K2高点上方1跳",
            "stop_loss_price": 99.0,
            "take_profit_price": 113.2,
            "take_profit_price_2": 118.0,
            "estimated_win_rate": 55,
        },
        "decision_trace": [
            {"node_id": "9.0", "answer": "是", "reason": "model says signal", "bar_range": "K2"},
            {"node_id": "10.3", "answer": "是", "reason": "metrics ok", "bar_range": "K2-K1"},
        ],
        "terminal": {"node_id": "10.3", "outcome": "trade", "label": "trade"},
    }


def test_signal_bar_closed_checks_actual_closed_flag() -> None:
    fill = judge_signal_bar_closed(2, _frame(signal_closed=False))
    assert fill.answer != "是"


def test_direction_mismatch_blocks_order_before_section11() -> None:
    out = _stage2_long_breakout()

    DecisionNodeEngine.apply_stage2(out, _frame(signal_type="bear"), {"cycle_position": "normal_channel"})

    assert out["decision"]["order_type"] == "不下单"
    node_92 = next(node for node in out["decision_trace"] if node["node_id"] == "9.2")
    assert node_92["answer"] == "否"
    assert not any(
        str(node.get("node_id", "")).startswith("11") and node.get("answer") == "是"
        for node in out["decision_trace"]
    )


def test_closed_directional_signal_allows_pending_breakout() -> None:
    out = _stage2_long_breakout()

    DecisionNodeEngine.apply_stage2(out, _frame(signal_type="bull"), {"cycle_position": "normal_channel"})

    assert out["decision"]["order_type"] == "突破单"
    assert any(
        node.get("node_id") == "11.2" and node.get("answer") == "是"
        for node in out["decision_trace"]
    )


def test_engine_exception_forces_technical_no_order(monkeypatch) -> None:
    obj = _stage2_long_breakout()

    def fail(*_args, **_kwargs):
        raise RuntimeError("geometry exploded")

    monkeypatch.setattr(DecisionNodeEngine, "apply_stage2", fail)
    out = normalize_stage2(
        obj,
        kline_frame=_frame(signal_type="bull"),
        stage1_json={"cycle_position": "normal_channel"},
    )

    assert out["decision"]["order_type"] == "不下单"
    assert out["terminal"]["node_id"] == "technical_error"
    assert out["terminal"]["outcome"] == "reject"
    assert out["setup_evidence"]["verification_status"] == "technical_error"
    assert not any(
        str(node.get("node_id", "")).startswith("11")
        and node.get("answer") == "是"
        and not node.get("skipped")
        for node in out["decision_trace"]
    )

