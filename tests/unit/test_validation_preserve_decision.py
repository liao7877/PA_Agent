"""Tests for preserving decision JSON when strict validation fails."""
from __future__ import annotations

import copy
import json

from pa_agent.ai.json_validator import Ok, ValidationError, try_extract_parsed_object
from tests.fixtures.validators import schema_test_validator
from tests.integration.conftest import VALID_STAGE2


def test_missing_terminal_label_is_fixed_but_malformed_no_order_prices_rejected() -> None:
    payload = copy.deepcopy(VALID_STAGE2)
    payload["terminal"] = {"node_id": "10.3", "outcome": "reject"}
    payload["decision"]["order_type"] = "不下单"
    payload["decision_trace"] = [
        {
            "node_id": "10.3",
            "question": "交易者方程是否通过？",
            "answer": "否",
            "reason": "盈亏比不足",
            "bar_range": "K1",
        },
    ]
    result = schema_test_validator().validate("stage2", json.dumps(payload, ensure_ascii=False))
    assert isinstance(result, ValidationError), result
    assert result.category == "c"
    assert "entry_price" in result.invalid_fields
    assert result.partial_obj is not None
    assert result.partial_obj["terminal"]["label"]


def test_partial_obj_attached_when_schema_still_fails() -> None:
    payload = copy.deepcopy(VALID_STAGE2)
    payload["decision"]["trade_confidence"] = "ultra"
    result = schema_test_validator().validate("stage2", json.dumps(payload, ensure_ascii=False))
    assert isinstance(result, ValidationError)
    assert result.partial_obj is not None
    assert result.partial_obj["decision"]["order_type"] == payload["decision"]["order_type"]
    extracted = try_extract_parsed_object("stage2", json.dumps(payload, ensure_ascii=False))
    assert extracted is not None
