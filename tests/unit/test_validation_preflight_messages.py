"""Unit tests for preflight failure message formatting."""
from __future__ import annotations

from pa_agent.ai.validation_messages import format_preflight_failure


def test_format_preflight_failure_bar_count():
    text = format_preflight_failure(
        {"failed_check": "bar_count_lt_20", "message": "only 12 closed bars"}
    )
    assert "已收盘K线不足20根" in text
    assert "only 12 closed bars" in text
    assert "20 根已收盘 K 线" in text


def test_format_preflight_failure_unknown_check():
    text = format_preflight_failure({"failed_check": "custom_check"})
    assert "custom_check" in text
