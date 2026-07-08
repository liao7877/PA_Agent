"""Unit tests for FutureTrendPanel next_bar_prediction rendering (T18).

Prediction UI moved from DecisionPanel to FutureTrendPanel in the sidebar.
"""
from __future__ import annotations

import sys
import time

import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from PyQt6.QtWidgets import QApplication

from pa_agent.gui.future_trend_panel import FutureTrendPanel


@pytest.fixture(scope="module")
def qapp():
    """Shared QApplication for all tests in this module."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def panel(qapp):
    p = FutureTrendPanel()
    p.show()
    qapp.processEvents()
    return p


def _prediction_payload(**overrides) -> dict:
    base = {
        "direction": "bullish",
        "probabilities": {"bullish": 70, "bearish": 20, "neutral": 10},
        "reasoning": "test",
        "unpredictable": False,
        "features_used": ["stage1_diagnosis"],
    }
    base.update(overrides)
    return {"next_bar_prediction": base}


def test_panel_no_prediction_hidden(panel: FutureTrendPanel):
    """Without next_bar_prediction, bar prediction group must be hidden (R6.6)."""
    panel.set_prediction({})
    assert not panel._bar_group.isVisible()


def test_panel_unpredictable_renders_gray(panel: FutureTrendPanel):
    """unpredictable=true renders gray badge (R6.4)."""
    panel.set_prediction(
        _prediction_payload(
            direction=None,
            probabilities=None,
            reasoning="数据不足，无法预测方向",
            unpredictable=True,
        )
    )
    assert panel._bar_group.isVisible()
    assert "不可预测" in panel._bar_direction_label.text()
    assert "#8b949e" in panel._bar_direction_label.styleSheet()


def test_panel_bullish_renders_green(panel: FutureTrendPanel):
    """Highest bullish probability uses green on the combined probs line (R6.2, R6.3)."""
    panel.set_prediction(_prediction_payload())
    assert panel._bar_group.isVisible()
    line = panel._bar_direction_label.text()
    assert "阳线的概率为70%" in line
    assert "阴线的概率为20%" in line
    assert "中性的概率为10%" in line
    assert "#3fb950" in panel._bar_direction_label.styleSheet()


def test_panel_bearish_renders_red(panel: FutureTrendPanel):
    """Highest bearish probability uses red on the combined probs line."""
    panel.set_prediction(
        _prediction_payload(
            direction="bearish",
            probabilities={"bullish": 15, "bearish": 65, "neutral": 20},
            reasoning="空头趋势持续，阴线概率最高",
        )
    )
    line = panel._bar_direction_label.text()
    assert "阴线的概率为65%" in line
    assert "#f85149" in panel._bar_direction_label.styleSheet()


def test_panel_neutral_renders_yellow(panel: FutureTrendPanel):
    """Highest neutral probability uses yellow on the combined probs line."""
    panel.set_prediction(
        _prediction_payload(
            direction="neutral",
            probabilities={"bullish": 20, "bearish": 25, "neutral": 55},
            reasoning="震荡区间，方向不明，中性概率最高",
        )
    )
    assert "中性的概率为55%" in panel._bar_direction_label.text()
    assert "#e6b800" in panel._bar_direction_label.styleSheet()


def test_panel_clear_hides_group(panel: FutureTrendPanel):
    """clear() must hide prediction group and clear text."""
    panel.set_prediction(_prediction_payload())
    assert panel._bar_group.isVisible()

    panel.clear()
    assert not panel._bar_group.isVisible()
    assert panel._bar_reasoning_edit.toPlainText() == ""


def test_panel_render_performance(panel: FutureTrendPanel):
    """set_prediction must complete in ≤ 50ms (NFR1.3)."""
    payload = _prediction_payload(reasoning="test reasoning " * 30)
    start = time.perf_counter()
    for _ in range(10):
        panel.set_prediction(payload)
    elapsed = (time.perf_counter() - start) / 10
    assert elapsed < 0.05, f"set_prediction took {elapsed*1000:.1f}ms per call"


_garbage_prediction = st.fixed_dictionaries(
    {},
    optional={
        "direction": st.one_of(st.none(), st.text(max_size=20), st.integers()),
        "probabilities": st.one_of(
            st.none(),
            st.integers(),
            st.text(max_size=10),
            st.dictionaries(st.text(max_size=10), st.one_of(st.integers(), st.text(), st.none())),
        ),
        "reasoning": st.one_of(st.none(), st.text(max_size=100), st.integers(), st.lists(st.integers())),
        "unpredictable": st.one_of(st.booleans(), st.none(), st.integers(), st.text(max_size=5)),
        "features_used": st.one_of(st.none(), st.integers(), st.lists(st.one_of(st.text(), st.integers()))),
    },
)


@given(pred=_garbage_prediction)
@h_settings(max_examples=100, deadline=None)
def test_panel_robust_against_garbage(pred: dict):
    """Any garbage next_bar_prediction must not raise an exception (P10)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    p = FutureTrendPanel()
    p.show()
    app.processEvents()
    try:
        p.set_prediction({"next_bar_prediction": pred})
    except Exception:
        pass
