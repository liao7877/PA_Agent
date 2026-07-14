"""Tests for empty-content fallback after thinking."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from pa_agent.ai.deepseek_client import AIReply, AIUsage
from pa_agent.config.settings import Settings
from pa_agent.orchestrator.two_stage import TwoStageOrchestrator, _stream_stage_with_empty_content_fallback
from pa_agent.util.threading import CancelToken, OrchestratorEvent
from tests.fixtures.ai_payloads import VALID_STAGE1, VALID_STAGE2_NO_ORDER
from tests.integration.conftest import make_frame


def _reply(content: str, reasoning: str = "") -> AIReply:
    return AIReply(
        content=content,
        reasoning_content=reasoning,
        raw={"content": content, "reasoning_content": reasoning},
        usage=AIUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req-1",
        latency_ms=100.0,
    )


def _json_reply(content_dict: dict) -> AIReply:
    text = json.dumps(content_dict, ensure_ascii=False)
    return _reply(text)


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


def test_retries_without_thinking_when_json_truncated() -> None:
    client = MagicMock()
    truncated = '{"decision":{"order_type":"不下单","reason":"等待'
    client.stream_chat.side_effect = [
        _reply(truncated, "long reasoning that consumed output budget"),
        _reply('{"decision":{"order_type":"不下单","reason":"等待信号"}}'),
    ]

    out = _stream_stage_with_empty_content_fallback(
        client,
        [{"role": "user", "content": "hi"}],
        stage="stage2",
        thinking=True,
        reasoning_effort="max",
        cancel_token=None,
        on_reasoning_token=None,
        on_content_token=None,
    )

    assert client.stream_chat.call_count == 2
    assert client.stream_chat.call_args_list[1].kwargs["thinking"] is False
    assert out.raw.get("fallback_reason") == "truncated_json_after_thinking"
    assert '"order_type"' in out.content


def test_stage1_validation_retry_uses_empty_content_fallback() -> None:
    client = MagicMock()
    first_invalid = dict(VALID_STAGE1)
    first_invalid.pop("gate_result", None)
    client.stream_chat.side_effect = [
        _json_reply(first_invalid),
        _reply("", "retry reasoning without json"),
        _json_reply(VALID_STAGE1),
        _json_reply(VALID_STAGE2_NO_ORDER),
    ]

    assembler = MagicMock()
    assembler.build_stage1.return_value = [{"role": "system", "content": "s1"}]
    assembler.build_stage2.return_value = [{"role": "system", "content": "s2"}]

    pending_writer = MagicMock()
    exp_reader = MagicMock()
    exp_reader.read_top5.return_value = []
    exp_reader.read_for_stage2.return_value = []

    settings = Settings()
    settings.provider.thinking = True
    settings.provider.reasoning_effort = "high"
    settings.validation.retry_max = 1
    settings.validation.retry_max_semantic = 1

    from pa_agent.ai.router import route_strategy_files
    from tests.fixtures.validators import schema_test_validator

    orchestrator = TwoStageOrchestrator(
        client=client,
        assembler=assembler,
        router=route_strategy_files,
        validator=schema_test_validator(),
        pending_writer=pending_writer,
        exp_reader=exp_reader,
        settings=settings,
    )

    events: list[OrchestratorEvent] = []
    record = orchestrator.submit(
        make_frame(),
        CancelToken(),
        events.append,
    )

    assert record.exception is None
    assert OrchestratorEvent.Stage1Retry in events
    assert client.stream_chat.call_count == 4
    assert client.stream_chat.call_args_list[2].kwargs["thinking"] is False
    assert pending_writer.save_full.called
