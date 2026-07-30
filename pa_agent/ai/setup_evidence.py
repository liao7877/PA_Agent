"""Objective price-action evidence for authorizing entry setups."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pa_agent.ai.market_features import SimpleMarketFeatures, compute_simple_market_features
from pa_agent.util.price_tick import bar_by_seq, parse_k_seq

RANGE_OVERLAP_MAX = 0.65


@dataclass(frozen=True)
class SetupEvidence:
    verified: bool
    setup_type: str
    reason: str
    signal_seq: int | None = None
    confirmation_seq: int | None = None
    anchor_price: float | None = None
    invalidation_price: float | None = None


def verify_setup_evidence(
    *,
    stage1_json: dict[str, Any] | None,
    stage2_json: dict[str, Any],
    frame: Any,
    market: SimpleMarketFeatures | None = None,
) -> SetupEvidence:
    decision = stage2_json.get("decision")
    bar_analysis = stage2_json.get("bar_analysis")
    if not isinstance(decision, dict) or not isinstance(bar_analysis, dict):
        return SetupEvidence(False, "unknown", "缺少 decision/bar_analysis")

    signal = bar_analysis.get("signal_bar")
    entry = bar_analysis.get("entry_bar")
    signal = signal if isinstance(signal, dict) else {}
    entry = entry if isinstance(entry, dict) else {}
    signal_seq = parse_k_seq(signal.get("bar"))
    confirmation_seq = parse_k_seq(entry.get("bar"))
    signal_bar = bar_by_seq(frame, signal_seq) if signal_seq is not None else None
    if signal_bar is None or not bool(getattr(signal_bar, "closed", False)):
        return SetupEvidence(False, "unknown", "信号棒不存在或未收盘", signal_seq)

    order_type = str(decision.get("order_type") or "")
    direction = str(decision.get("order_direction") or "")
    setup_type = str(bar_analysis.get("entry_setup_type") or signal.get("pattern") or "").strip().lower()
    market = market or compute_simple_market_features(frame)
    cycle = str((stage1_json or {}).get("cycle_position") or "")

    if cycle == "trading_range":
        if market.range_high is None or market.range_low is None or market.zone == "unknown":
            return SetupEvidence(False, setup_type or "tr_boundary", "交易区间缺少客观边界", signal_seq)
        if market.zone == "middle_third":
            return SetupEvidence(False, setup_type or "tr_boundary", "价格位于交易区间中部", signal_seq)
        if market.barbwire_candidate or (market.overlap_mean_10 or 0.0) > RANGE_OVERLAP_MAX:
            return SetupEvidence(False, setup_type or "tr_boundary", "铁丝网/高重叠环境禁止入场", signal_seq)
        if direction == "做多" and market.zone != "lower_third":
            return SetupEvidence(False, setup_type or "tr_boundary", "区间做多必须位于客观下沿", signal_seq)
        if direction == "做空" and market.zone != "upper_third":
            return SetupEvidence(False, setup_type or "tr_boundary", "区间做空必须位于客观上沿", signal_seq)

    if order_type == "突破单":
        basis_seq = parse_k_seq(decision.get("entry_basis_bar"))
        if basis_seq != signal_seq:
            return SetupEvidence(False, "breakout_signal", "突破基准棒必须与已验证信号棒一致", signal_seq)
        extreme = "high" if direction == "做多" else "low"
        anchor = float(getattr(signal_bar, extreme))
        invalidation = float(getattr(signal_bar, "low" if direction == "做多" else "high"))
        return SetupEvidence(True, "breakout_signal", "已收盘方向信号允许等待极点突破", signal_seq, None, anchor, invalidation)

    if order_type == "市价单":
        confirmation = bar_by_seq(frame, confirmation_seq) if confirmation_seq is not None else None
        if confirmation is None or not bool(getattr(confirmation, "closed", False)):
            return SetupEvidence(False, "market_confirmation", "市价单缺少已收盘确认棒", signal_seq, confirmation_seq)
        if signal_seq is None or confirmation_seq >= signal_seq:
            return SetupEvidence(False, "market_confirmation", "确认棒必须晚于信号棒", signal_seq, confirmation_seq)
        invalidation = float(getattr(signal_bar, "low" if direction == "做多" else "high"))
        return SetupEvidence(True, "market_confirmation", "已验证市价确认 chronology", signal_seq, confirmation_seq, None, invalidation)

    if order_type == "限价单":
        if setup_type in ("h2", "l2"):
            want = "h2" if direction == "做多" else "l2"
            candidate = market.hl_count.bull_candidate if direction == "做多" else market.hl_count.bear_candidate
            if setup_type != want or candidate not in (want, "h3" if want == "h2" else "l3"):
                return SetupEvidence(False, setup_type, f"缺少客观 {want.upper()} 计数证据", signal_seq, confirmation_seq)
        elif setup_type in ("breakout_pullback", "breakout_retest"):
            events = market.breakout_events
            has_breakout = any(event.event == "breakout" for event in events)
            has_test = any(event.event == "test" for event in events)
            if not (has_breakout and has_test):
                return SetupEvidence(False, setup_type, "缺少先突破后回测的客观事件链", signal_seq, confirmation_seq)
        else:
            return SetupEvidence(False, setup_type or "unknown", "限价单仅允许客观回测/H2/L2结构", signal_seq, confirmation_seq)
        if confirmation_seq is None or signal_seq is None or confirmation_seq >= signal_seq:
            return SetupEvidence(False, setup_type, "限价确认棒 chronology 无效", signal_seq, confirmation_seq)
        confirmation = bar_by_seq(frame, confirmation_seq)
        if confirmation is None or not bool(getattr(confirmation, "closed", False)):
            return SetupEvidence(False, setup_type, "限价确认棒不存在或未收盘", signal_seq, confirmation_seq)
        invalidation = float(getattr(confirmation, "low" if direction == "做多" else "high"))
        return SetupEvidence(True, setup_type, "客观结构与 chronology 已验证", signal_seq, confirmation_seq, None, invalidation)

    return SetupEvidence(False, setup_type or "unknown", "不是可授权订单类型", signal_seq, confirmation_seq)
