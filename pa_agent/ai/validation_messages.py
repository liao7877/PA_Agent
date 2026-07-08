"""Human-readable labels for validation error prefixes (P0-3)."""
from __future__ import annotations

PREFLIGHT_FAILED_CHECK_LABELS: dict[str, str] = {
    "bars_empty_or_bad_ohlc": "K线数据为空或OHLC异常",
    "bar_count_lt_20": "已收盘K线不足20根",
    "indicators_all_nan": "EMA20/ATR14全为NaN（指标预热不足）",
}

_PREFIX_RULES: tuple[tuple[str, str], ...] = (
    ("gate:", "【闸门】"),
    ("gate_trace", "【闸门路径】"),
    ("coherence:", "【一致性】"),
    ("s1:", "【阶段一】"),
    ("s2:", "【阶段二】"),
    ("trace:", "【决策路径】"),
    ("metrics:", "【盈亏比/方程】"),
    ("limit long:", "【限价做多·K1】"),
    ("limit short:", "【限价做空·K1】"),
    ("breakout_price:", "【突破价】"),
    ("signal_chain:", "【信号链】"),
    ("next_bar_prediction", "【下一根预期】"),
    ("bar_by_bar", "【逐棒摘要】"),
    ("diagnosis_summary", "【诊断摘要】"),
    ("order_direction", "【下单方向】"),
    ("always_in", "【AIL状态】"),
    ("terminal.outcome", "【终局结果】"),
    ("terminal", "【终局】"),
    ("placing an order", "【下单规则】"),
    ("incremental", "【增量分析】"),
    ("provider:quota_exhausted", "【API 额度】"),
)


def format_preflight_failure(exc_info: dict) -> str:
    """Short Chinese summary for insufficient_data exceptions."""
    failed_check = str(exc_info.get("failed_check", "") or "")
    label = PREFLIGHT_FAILED_CHECK_LABELS.get(failed_check, failed_check or "数据不足")
    message = str(exc_info.get("message", "") or "").strip()
    lines = [f"原因：{label}"]
    if message and message not in label:
        lines.append(message)
    lines.append("请等待图表加载足够 K 线后重新提交（至少需要 20 根已收盘 K 线）。")
    return "\n".join(lines)


def format_validation_errors(
    invalid_fields: list[str],
    *,
    missing_fields: list[str] | None = None,
    max_items: int = 8,
) -> str:
    """Build a short Chinese summary for status bar / exception message."""
    lines: list[str] = []
    if missing_fields:
        lines.append("缺少字段: " + ", ".join(missing_fields[:max_items]))
    for raw in invalid_fields[:max_items]:
        lines.append(_label_one(raw))
    extra = len(invalid_fields) - max_items
    if extra > 0:
        lines.append(f"…另有 {extra} 条")
    return "；".join(lines) if lines else ""


def format_preflight_failure(exc_info: dict) -> str:
    """Short Chinese summary for insufficient_data exceptions."""
    failed_check = str(exc_info.get("failed_check", "") or "")
    label = PREFLIGHT_FAILED_CHECK_LABELS.get(failed_check, failed_check or "数据不足")
    message = str(exc_info.get("message", "") or "").strip()
    lines = [f"原因：{label}"]
    if message and message not in label:
        lines.append(message)
    lines.append("请等待图表加载足够 K 线后重新提交（至少需要 20 根已收盘 K 线）。")
    return "\n".join(lines)


def _label_one(raw: str) -> str:
    text = str(raw).strip()
    for prefix, label in _PREFIX_RULES:
        if text.startswith(prefix) or prefix in text:
            body = text.split(":", 1)[-1].strip() if ":" in text else text
            return f"{label}{body}"
    return text
