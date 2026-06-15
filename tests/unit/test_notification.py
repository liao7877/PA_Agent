"""Unit tests for the notification module.

Covers message formatting, scene classification, per-scene toggle filtering,
channel payload construction, and DingTalk signing — all without real HTTP.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from pa_agent.config.settings import NotificationSettings, Settings
from pa_agent.notification import formatter
from pa_agent.notification.channels import DingTalkChannel, WeChatChannel
from pa_agent.notification.events import NotificationEvent, NotificationMessage
from pa_agent.notification.service import NotificationService


# ── Formatter ─────────────────────────────────────────────────────────────────
def test_classify_new_order_vs_no_trade():
    trade = {"decision": {"order_type": "限价单"}}
    wait = {"decision": {"order_type": "不下单"}}
    assert formatter.classify_decision(trade) is NotificationEvent.NEW_ORDER
    assert formatter.classify_decision(wait) is NotificationEvent.NO_TRADE


def test_format_decision_new_order_includes_prices():
    decision = {
        "decision": {
            "order_type": "限价单",
            "order_direction": "做多",
            "entry_price": 2350.5,
            "take_profit_price": 2360.0,
            "stop_loss_price": 2345.0,
            "reasoning": "趋势回踩支撑",
            "diagnosis_confidence": 72,
            "trade_confidence": 65,
        },
        "diagnosis_summary": {
            "direction": "bullish",
            "cycle_position": "normal_channel",
            "market_phase": "stable",
        },
    }
    msg = formatter.format_decision(symbol="XAUUSD", timeframe="15m", decision=decision)
    assert msg.event is NotificationEvent.NEW_ORDER
    assert "做多" in msg.title
    assert "2350.5" in msg.text
    assert "2360" in msg.text
    assert "2345" in msg.text
    assert "市场诊断" in msg.text
    assert "72/100" in msg.text
    assert msg.plain_text
    assert msg.fields["entry_price"] == 2350.5


def test_format_decision_no_trade_includes_watch_points():
    decision = {
        "decision": {
            "order_type": "不下单",
            "reasoning": "区间震荡观望",
            "watch_points": [
                "回撤至 2350 附近出现反转信号再评估做多",
            ],
        },
    }
    msg = formatter.format_decision(symbol="XAUUSD", timeframe="15m", decision=decision)
    assert "关注要点" in msg.text
    assert "2350" in msg.text


def test_format_decision_no_trade():
    decision = {
        "decision": {
            "order_type": "不下单",
            "reasoning": "区间震荡观望",
            "diagnosis_confidence": 72,
            "diagnosis_confidence_reasoning": "结构不清晰",
            "trade_confidence": 45,
            "trade_confidence_reasoning": "信号不足",
        },
        "diagnosis_summary": {
            "direction": "neutral",
            "cycle_position": "trending_tr",
            "market_phase": "transitioning",
            "transition_risk": "high",
        },
    }
    msg = formatter.format_decision(symbol="XAUUSD", timeframe="15m", decision=decision)
    assert msg.event is NotificationEvent.NO_TRADE
    assert "观望" in msg.title
    assert "不下单" in msg.text
    assert "趋势型交易区间" in msg.text
    assert "过渡" in msg.text
    assert "分析理由" in msg.text


def test_format_error():
    exc = {"category": "b", "stage": "stage2", "message": "JSON 截断"}
    msg = formatter.format_error(symbol="XAUUSD", timeframe="15m", exception=exc)
    assert msg.event is NotificationEvent.ERROR
    assert "异常" in msg.title


def test_format_api_error():
    msg = formatter.format_api_error(
        message="401 Unauthorized",
        symbol="XAUUSD",
        timeframe="15m",
        stage="stage1",
        source="analysis",
    )
    assert msg.event is NotificationEvent.API_ERROR
    assert "API 异常" in msg.title
    assert "401" in msg.text


def test_is_api_exception_dict():
    assert formatter.is_api_exception({"type": "api_error", "message": "boom"})
    assert formatter.is_api_exception({"type": "network_error", "message": "boom"})
    assert not formatter.is_api_exception({"type": "validation_error", "message": "boom"})


def test_format_entry_exit_manage():
    filled = formatter.format_entry_filled(
        symbol="XAUUSD", timeframe="15m", direction="做多", entry_price=2350,
    )
    assert filled.event is NotificationEvent.ENTRY_FILLED
    exited = formatter.format_exit(
        symbol="XAUUSD", timeframe="15m", direction="做多", reason="触及止盈",
        exit_price=2360,
    )
    assert exited.event is NotificationEvent.EXIT
    managed = formatter.format_manage(
        symbol="XAUUSD", timeframe="15m", direction="做多", change_text="止损移动到保本",
        stop_loss_price=2350,
    )
    assert managed.event is NotificationEvent.MANAGE


# ── Service toggle filtering ──────────────────────────────────────────────────
class _RecordingService(NotificationService):
    """Capture dispatched messages instead of sending over HTTP."""

    def __init__(self, settings):
        super().__init__(settings=settings)
        self.dispatched: list = []

    def _dispatch_sync(self, channels, message):  # noqa: D401
        self.dispatched.append(message)


def _settings_with(**notif_kwargs) -> Settings:
    s = Settings()
    s.notification = NotificationSettings(**notif_kwargs)
    return s


def test_master_switch_off_blocks_everything():
    s = _settings_with(enabled=False, dingtalk_webhook="https://x", notify_new_order=True)
    svc = _RecordingService(s)
    msg = NotificationMessage(NotificationEvent.NEW_ORDER, "t", "b")
    svc.notify(msg)
    assert svc.dispatched == []


def test_scene_toggle_off_blocks_that_scene():
    s = _settings_with(
        enabled=True, dingtalk_webhook="https://x",
        notify_new_order=True, notify_no_trade=False,
    )
    svc = _RecordingService(s)
    svc.notify(NotificationMessage(NotificationEvent.NO_TRADE, "t", "b"))
    assert svc.dispatched == []
    svc.notify(NotificationMessage(NotificationEvent.NEW_ORDER, "t", "b"))
    assert len(svc.dispatched) == 1


def test_no_channel_configured_skips():
    s = _settings_with(enabled=True, notify_new_order=True)
    svc = _RecordingService(s)
    svc.notify(NotificationMessage(NotificationEvent.NEW_ORDER, "t", "b"))
    assert svc.dispatched == []


def test_notify_record_no_trade_respects_scene_toggle():
    s = _settings_with(
        enabled=True, wechat_webhook="https://x",
        notify_no_trade=False,
    )
    svc = _RecordingService(s)
    rec = SimpleNamespace(
        meta=SimpleNamespace(symbol="XAUUSD", timeframe="15m"),
        exception=None,
        stage2_decision={
            "decision": {
                "order_type": "不下单",
                "reasoning": "等待确认",
                "watch_points": ["回撤至 2350 评估做多"],
            }
        },
        stage1_diagnosis=None,
    )
    svc.notify_record(rec)
    assert svc.dispatched == []

    s.notification.notify_no_trade = True
    svc.notify_record(rec)
    assert svc.dispatched[-1].event is NotificationEvent.NO_TRADE
    assert "2350" in svc.dispatched[-1].text


def test_notify_api_error_toggle_blocks_api_failures():
    s = _settings_with(
        enabled=True,
        dingtalk_webhook="https://x",
        notify_api_error=False,
    )
    svc = _RecordingService(s)
    svc.notify_api_failure(message="timeout", stage="stage1")
    assert svc.dispatched == []

    s.notification.notify_api_error = True
    svc.notify_api_failure(message="timeout", stage="stage1")
    assert svc.dispatched[-1].event is NotificationEvent.API_ERROR


def test_notify_record_routes_api_error_separately_from_validation_error():
    s = _settings_with(
        enabled=True,
        wechat_webhook="https://x",
        notify_api_error=True,
        notify_error=False,
    )
    svc = _RecordingService(s)
    rec = SimpleNamespace(
        meta=SimpleNamespace(symbol="XAUUSD", timeframe="15m"),
        exception={"type": "api_error", "stage": "stage2", "message": "429 Too Many Requests"},
        stage2_decision=None,
    )
    svc.notify_record(rec)
    assert svc.dispatched[-1].event is NotificationEvent.API_ERROR
    assert "429" in svc.dispatched[-1].text


def test_notify_record_routes_error_and_decision():
    s = _settings_with(
        enabled=True, wechat_webhook="https://x",
        notify_new_order=True, notify_error=True,
    )
    svc = _RecordingService(s)

    rec_err = SimpleNamespace(
        meta=SimpleNamespace(symbol="XAUUSD", timeframe="15m"),
        exception={"category": "b", "message": "boom"},
        stage2_decision=None,
    )
    svc.notify_record(rec_err)
    assert svc.dispatched[-1].event is NotificationEvent.ERROR

    rec_dec = SimpleNamespace(
        meta=SimpleNamespace(symbol="XAUUSD", timeframe="15m"),
        exception=None,
        stage2_decision={"decision": {"order_type": "限价单", "order_direction": "做多",
                                      "entry_price": 1, "take_profit_price": 2,
                                      "stop_loss_price": 0.5}},
    )
    svc.notify_record(rec_dec)
    assert svc.dispatched[-1].event is NotificationEvent.NEW_ORDER


def test_notify_record_sends_error_when_metrics_reject_trade():
    s = _settings_with(
        enabled=True, wechat_webhook="https://x",
        notify_new_order=True, notify_error=True,
    )
    svc = _RecordingService(s)
    rec = SimpleNamespace(
        meta=SimpleNamespace(symbol="XAUUSD", timeframe="5m"),
        exception={
            "type": "validation_error",
            "stage": "stage2",
            "category": "c",
            "invalid_fields": ["metrics:盈亏比不达标"],
            "decision_preserved": True,
        },
        stage2_decision={
            "decision": {
                "order_type": "市价单",
                "order_direction": "做空",
                "entry_price": 1.0,
                "take_profit_price": 0.5,
                "stop_loss_price": 2.0,
            }
        },
        stage1_diagnosis=None,
    )
    svc.notify_record(rec)
    assert svc.dispatched[-1].event is NotificationEvent.ERROR


def test_notify_record_sends_decision_when_validation_preserved():
    s = _settings_with(
        enabled=True, wechat_webhook="https://x",
        notify_new_order=True, notify_error=True,
    )
    svc = _RecordingService(s)
    rec = SimpleNamespace(
        meta=SimpleNamespace(symbol="XAUUSD", timeframe="5m"),
        exception={
            "type": "validation_error",
            "stage": "stage2",
            "category": "c",
            "message": "signal_chain:market order requires a concrete entry_bar.bar",
            "decision_preserved": True,
        },
        stage2_decision={
            "decision": {
                "order_type": "市价单",
                "order_direction": "做空",
                "entry_price": 4278.76,
                "take_profit_price": 4235.0,
                "stop_loss_price": 4297.02,
                "reasoning": "追空",
            }
        },
        stage1_diagnosis=None,
    )
    svc.notify_record(rec)
    assert len(svc.dispatched) == 1
    assert svc.dispatched[0].event is NotificationEvent.NEW_ORDER
    assert "市价单" in svc.dispatched[0].text


# ── Channel payloads ──────────────────────────────────────────────────────────
def test_dingtalk_payload_is_action_card():
    ch = DingTalkChannel(webhook="https://oapi.dingtalk.com/robot/send?access_token=abc")
    msg = NotificationMessage(NotificationEvent.NEW_ORDER, "标题", "### 正文内容")
    req = ch._build_request(msg)
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["msgtype"] == "actionCard"
    assert payload["actionCard"]["title"] == "标题"
    assert "正文内容" in payload["actionCard"]["text"]


def test_dingtalk_signing_appends_params():
    ch = DingTalkChannel(
        webhook="https://oapi.dingtalk.com/robot/send?access_token=abc",
        secret="SECxxxx",
    )
    url = ch._signed_url()
    assert "timestamp=" in url
    assert "sign=" in url


def test_dingtalk_no_secret_keeps_url():
    ch = DingTalkChannel(webhook="https://oapi.dingtalk.com/robot/send?access_token=abc")
    assert ch._signed_url() == "https://oapi.dingtalk.com/robot/send?access_token=abc"


def test_wechat_payload_has_title_and_body():
    ch = WeChatChannel(webhook="https://api.day.app/xxxx")
    msg = NotificationMessage(
        NotificationEvent.EXIT,
        "出场",
        "### markdown",
        plain_text="止盈出场",
    )
    req = ch._build_request(msg)
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["title"] == "出场"
    assert payload["body"] == "止盈出场"
    assert "出场" in payload["content"]


def test_dingtalk_interpret_errcode_failure():
    ch = DingTalkChannel(webhook="https://x")
    res = ch._interpret_response(200, json.dumps({"errcode": 310000, "errmsg": "keyword"}))
    assert res.ok is False
    res_ok = ch._interpret_response(200, json.dumps({"errcode": 0}))
    assert res_ok.ok is True


# ── Settings round-trip ───────────────────────────────────────────────────────
def test_notification_settings_round_trip(tmp_path):
    from pa_agent.config.settings import load_settings, save_settings

    p = tmp_path / "settings.json"
    s = Settings()
    s.notification.enabled = True
    s.notification.dingtalk_webhook = "https://oapi.dingtalk.com/robot/send?access_token=x"
    s.notification.notify_no_trade = True
    save_settings(s, p)
    loaded = load_settings(p)
    assert loaded.notification.enabled is True
    assert loaded.notification.dingtalk_webhook.endswith("access_token=x")
    assert loaded.notification.notify_no_trade is True
