"""Integration: Stage1 gate wait short-circuits Stage2 API call."""
from __future__ import annotations

import copy
from unittest.mock import MagicMock

from tests.fixtures.validators import schema_test_validator
from pa_agent.ai.router import route_strategy_files
from pa_agent.orchestrator.two_stage import TwoStageOrchestrator
from pa_agent.util.threading import CancelToken, OrchestratorEvent

from .conftest import VALID_STAGE1, VALID_STAGE2, make_reply


def test_gate_wait_skips_stage2_chat(
    frame, pending_writer, assembler, exp_reader,
) -> None:
    stage1_wait = copy.deepcopy(VALID_STAGE1)
    stage1_wait["gate_result"] = "wait"
    stage1_wait["gate_trace"] = [
        {
            "node_id": "1.2",
            "question": "是否能识别市场周期？",
            "answer": "否",
            "action": "等待",
            "reason": "无法识别周期",
            "bar_range": "K5-K1",
        }
    ]
    stage1_wait["cycle_position"] = "unknown"

    client = MagicMock()
    client.stream_chat.return_value = make_reply(stage1_wait)

    orchestrator = TwoStageOrchestrator(
        client=client,
        assembler=assembler,
        router=route_strategy_files,
        validator=schema_test_validator(),
        pending_writer=pending_writer,
        exp_reader=exp_reader,
    )

    events: list[OrchestratorEvent] = []
    record = orchestrator.submit(
        frame=frame,
        cancel_token=CancelToken(),
        on_event=events.append,
    )

    assert client.stream_chat.call_count == 1
    assert record.stage2_decision is not None
    assert record.stage2_decision.get("gate_shortcircuited") is True
    assert record.stage2_decision["decision"]["order_type"] == "不下单"
    assert OrchestratorEvent.Stage2Done in events


def test_gate_wait_still_calls_stage2_to_manage_planned_order(
    frame, pending_writer, assembler, exp_reader,
) -> None:
    stage1_wait = copy.deepcopy(VALID_STAGE1)
    stage1_wait["gate_result"] = "wait"
    stage1_wait["gate_trace"] = [
        {
            "node_id": "1.2",
            "question": "是否能识别市场周期？",
            "answer": "否",
            "action": "等待",
            "reason": "无法识别周期",
            "bar_range": "K5-K1",
        }
    ]
    stage1_wait["cycle_position"] = "unknown"
    manage_decision = copy.deepcopy(VALID_STAGE2)
    manage_decision["decision"] = {
        "order_direction": None,
        "order_type": "不下单",
        "entry_price": None,
        "take_profit_price": None,
        "take_profit_price_2": None,
        "stop_loss_price": None,
        "entry_basis_bar": None,
        "entry_basis_extreme": None,
        "entry_rule": None,
        "position_action": "撤销",
        "position_advice": "市场结构无法识别，撤销原计划单。",
        "reasoning": "原计划依据已不可靠。",
        "diagnosis_confidence": 30,
        "diagnosis_confidence_reasoning": "周期无法识别",
        "trade_confidence": 0,
        "trade_confidence_reasoning": "不再执行原计划",
        "estimated_win_rate": None,
        "estimated_win_rate_reasoning": "不适用",
        "key_factors": ["周期无法识别"],
        "watch_points": ["等待结构恢复"],
        "risk_assessment": "继续保留旧挂单风险过高",
        "invalidation_condition": None,
    }

    client = MagicMock()
    client.stream_chat.side_effect = [make_reply(stage1_wait), make_reply(manage_decision)]
    orchestrator = TwoStageOrchestrator(
        client=client,
        assembler=assembler,
        router=route_strategy_files,
        validator=schema_test_validator(),
        pending_writer=pending_writer,
        exp_reader=exp_reader,
    )
    active_position = {
        "status": "planned",
        "symbol": frame.symbol,
        "timeframe": frame.timeframe,
        "order_direction": "做多",
        "order_type": "限价单",
        "entry_price": 2000.0,
        "take_profit_price": 2050.0,
        "stop_loss_price": 1980.0,
    }

    record = orchestrator.submit(
        frame=frame,
        cancel_token=CancelToken(),
        on_event=lambda _event: None,
        active_position=active_position,
    )

    assert client.stream_chat.call_count == 2
    assert record.stage2_decision["decision"]["position_action"] == "撤销"
    assert assembler.build_stage2_continuation.call_args.kwargs["active_position"] == active_position
