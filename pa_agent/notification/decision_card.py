"""Rich card-style markdown for decision notifications (mirrors DecisionPanel)."""
from __future__ import annotations

from typing import Any

from pa_agent.util.trade_metrics import (
    compute_risk_reward,
    format_estimated_win_rate,
    passes_trader_equation,
)

_NO_ORDER = "不下单"

_CYCLE_POSITION_ZH: dict[str, str] = {
    "spike": "尖峰 (Spike)",
    "micro_channel": "微型通道",
    "tight_channel": "窄通道",
    "normal_channel": "正常通道",
    "broad_channel": "宽通道",
    "trending_tr": "趋势型交易区间",
    "trading_range": "交易区间",
    "extreme_tr": "极端交易区间",
    "unknown": "未知",
}

_RANGE_CYCLES = frozenset({"trading_range", "extreme_tr", "trending_tr"})

_MARKET_PHASE_ZH: dict[str, str] = {
    "stable": "稳定",
    "transitioning": "过渡",
}


def _format_cycle_position(raw: str) -> str:
    key = (raw or "").strip().lower()
    return _CYCLE_POSITION_ZH.get(key, raw or "—")


def _format_market_phase(raw: str) -> str:
    key = (raw or "").strip().lower()
    return _MARKET_PHASE_ZH.get(key, raw or "—")


def _infer_trend_label(direction: str, cycle_position: str) -> str:
    cp = (cycle_position or "").strip().lower()
    d = (direction or "").strip().lower()
    if cp in _RANGE_CYCLES:
        return "震荡"
    if d == "bullish":
        return "上涨"
    if d == "bearish":
        return "下跌"
    if d == "neutral":
        return "震荡"
    if cp in ("spike", "micro_channel", "tight_channel"):
        return "趋势运行中"
    return "—"


def _parse_score_100(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return max(0, min(100, int(value)))
    try:
        return max(0, min(100, int(float(str(value).strip()))))
    except (ValueError, TypeError):
        return None


def _progress_bar(score: int, *, width: int = 20) -> str:
    filled = max(0, min(width, round(score / 100 * width)))
    return f"{'█' * filled}{'░' * (width - filled)} {score}/100"


def _fmt_price(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _merge_diagnosis(
    diagnosis_summary: dict | None,
    stage1_diagnosis: dict | None,
) -> dict:
    src: dict = {}
    if diagnosis_summary:
        src.update(diagnosis_summary)
    if stage1_diagnosis:
        for k, v in stage1_diagnosis.items():
            src.setdefault(k, v)
    return src


def build_decision_card(
    *,
    symbol: str,
    timeframe: str,
    decision_root: dict,
    stage1_diagnosis: dict | None = None,
) -> tuple[str, str, str]:
    """Return ``(title, markdown_text, plain_text)`` for a stage-2 decision."""
    inner = (
        decision_root.get("decision", decision_root)
        if isinstance(decision_root, dict)
        else {}
    )
    diagnosis_summary = (
        decision_root.get("diagnosis_summary")
        if isinstance(decision_root, dict)
        else None
    )
    diag = _merge_diagnosis(diagnosis_summary, stage1_diagnosis)

    pair = f"{symbol} {timeframe}".strip()
    order_type = str(inner.get("order_type") or _NO_ORDER)
    no_order = order_type == _NO_ORDER
    direction = str(inner.get("order_direction") or "")
    reasoning = str(inner.get("reasoning") or inner.get("brief_reasoning") or "").strip()

    trend = _infer_trend_label(
        str(diag.get("direction", "") or ""),
        str(diag.get("cycle_position", "") or ""),
    )
    cycle_zh = _format_cycle_position(str(diag.get("cycle_position", "") or ""))
    alt_cycle = diag.get("alternative_cycle_position")
    if alt_cycle:
        cycle_zh += f"（备选 {_format_cycle_position(str(alt_cycle))}）"

    market_phase = str(diag.get("market_phase", "") or "")
    phase_line = "—"
    if market_phase:
        phase_line = _format_market_phase(market_phase)
        risk = diag.get("transition_risk")
        if market_phase == "transitioning" and risk:
            phase_line += f" · 风险 {risk}"

    diag_conf = _parse_score_100(inner.get("diagnosis_confidence"))
    diag_conf_reason = str(inner.get("diagnosis_confidence_reasoning") or "").strip()
    trade_conf = _parse_score_100(inner.get("trade_confidence"))
    trade_conf_reason = str(inner.get("trade_confidence_reasoning") or "").strip()

    if no_order:
        title = f"⏸ 观望 · {pair}"
        decision_head = f"**{order_type}**"
        if trade_conf is not None:
            decision_head += f" · 置信度 {trade_conf}/100 · 观望"
    else:
        title = f"📈 {order_type} · {pair} · {direction or '—'}"
        decision_head = f"**{order_type}** · 方向 **{direction or '—'}**"
        if trade_conf is not None:
            decision_head += f" · 置信度 {trade_conf}/100 · 入场"

    md_lines: list[str] = [
        f"## AI 交易决策 · {pair}",
        "",
        "> 分析仅供参考，不构成投资建议",
        "",
        "---",
        "",
        "### 市场诊断",
        "",
        f"- **趋势** {trend}",
        f"- **周期** {cycle_zh}",
        f"- **阶段** {phase_line}",
        "",
    ]

    plain_lines: list[str] = [
        f"AI 交易决策 · {pair}",
        "分析仅供参考，不构成投资建议",
        "",
        "【市场诊断】",
        f"趋势: {trend}",
        f"周期: {cycle_zh}",
        f"阶段: {phase_line}",
        "",
    ]

    if diag_conf is not None:
        bar = _progress_bar(diag_conf)
        md_lines.extend([
            "### 市场判断置信度",
            "",
            bar,
            "",
        ])
        plain_lines.extend([
            "【市场判断置信度】",
            bar,
            "",
        ])
        if diag_conf_reason:
            md_lines.append(f"理由：{_truncate(diag_conf_reason, 300)}")
            md_lines.append("")
            plain_lines.append(f"理由: {_truncate(diag_conf_reason, 300)}")
            plain_lines.append("")

    md_lines.extend([
        "---",
        "",
        "### 交易决策",
        "",
        decision_head,
        "",
    ])
    plain_lines.extend([
        "【交易决策】",
        decision_head.replace("**", ""),
        "",
    ])

    if trade_conf_reason:
        md_lines.append(f"置信度理由：{_truncate(trade_conf_reason, 300)}")
        md_lines.append("")
        plain_lines.append(f"置信度理由: {_truncate(trade_conf_reason, 300)}")
        plain_lines.append("")

    if not no_order:
        entry = inner.get("entry_price")
        tp = inner.get("take_profit_price")
        sl = inner.get("stop_loss_price")
        md_lines.extend([
            f"- 入场 **{_fmt_price(entry)}**",
            f"- 止盈 **{_fmt_price(tp)}**",
            f"- 止损 **{_fmt_price(sl)}**",
            "",
        ])
        plain_lines.extend([
            f"入场: {_fmt_price(entry)}",
            f"止盈: {_fmt_price(tp)}",
            f"止损: {_fmt_price(sl)}",
            "",
        ])

        rr = compute_risk_reward(entry, tp, sl, direction)
        if rr is not None:
            win_pct = _parse_score_100(inner.get("estimated_win_rate"))
            eq_note = ""
            if win_pct is not None:
                eq_ok = passes_trader_equation(win_pct, float(rr["risk"]), float(rr["reward"]))
                eq_note = " · 方程通过" if eq_ok else " · 方程不通过"
            rr_line = (
                f"盈亏比 **{rr['ratio_text']}**"
                f"（风险 {float(rr['risk']):.4g} / 回报 {float(rr['reward']):.4g}）"
                f"{eq_note}"
            )
            md_lines.append(rr_line)
            md_lines.append("")
            plain_lines.append(rr_line.replace("**", ""))
            plain_lines.append("")

        win_rate = format_estimated_win_rate(inner)
        if win_rate:
            md_lines.append(f"预估胜率 **{win_rate}**")
            md_lines.append("")
            plain_lines.append(f"预估胜率: {win_rate}")
            plain_lines.append("")

    if reasoning:
        md_lines.extend([
            "### 分析理由",
            "",
            _truncate(reasoning, 600),
        ])
        plain_lines.extend([
            "【分析理由】",
            _truncate(reasoning, 600),
        ])

    return title, "\n".join(md_lines).strip(), "\n".join(plain_lines).strip()
