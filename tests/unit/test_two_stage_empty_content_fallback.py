"""Tests for empty-content fallback after thinking."""
from __future__ import annotations

from unittest.mock import MagicMock

from pa_agent.ai.deepseek_client import AIReply, AIUsage
from pa_agent.orchestrator.two_stage import _stream_stage_with_empty_content_fallback


def _reply(content: str, reasoning: str = "") -> AIReply:
    return AIReply(
        content=content,
        reasoning_content=reasoning,
        raw={"content": content, "reasoning_content": reasoning},
        usage=AIUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req-1",
        latency_ms=100.0,
    )


def test_retries_without_thinking_when_content_empty() -> None:
    client = MagicMock()
    client.stream_chat.side_effect = [
        _reply("", "long reasoning without json"),
        _reply('{"cycle_position":"spike","direction":"bullish"}'),
    ]

    out = _stream_stage_with_empty_content_fallback(
        client,
        [{"role": "user", "content": "hi"}],
        stage="stage1",
        thinking=True,
        reasoning_effort="high",
        cancel_token=None,
        on_reasoning_token=None,
        on_content_token=None,
    )

    assert client.stream_chat.call_count == 2
    assert client.stream_chat.call_args_list[1].kwargs["thinking"] is False
    assert '"cycle_position"' in out.content
    assert out.raw.get("empty_content_fallback") is True
    assert out.usage.completion_tokens == 10
