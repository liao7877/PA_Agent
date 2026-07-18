"""Trading decision stance profiles for Stage 2 prompt injection."""
from __future__ import annotations

from typing import Literal

DecisionStance = Literal["conservative", "balanced", "aggressive", "extreme_aggressive"]

STANCE_LABELS_ZH: dict[str, str] = {
    "conservative": "保守",
    "balanced": "均衡",
    "aggressive": "激进",
    "extreme_aggressive": "极度激进",
}

_STANCE_ALIASES: dict[str, DecisionStance] = {
    "conservative": "conservative",
    "保守": "conservative",
    "balanced": "balanced",
    "均衡": "balanced",
    "aggressive": "aggressive",
    "激进": "aggressive",
    "extreme_aggressive": "extreme_aggressive",
    "extreme": "extreme_aggressive",
    "极度激进": "extreme_aggressive",
}


def normalize_stance(value: str | None) -> DecisionStance:
    """Coerce settings/UI value to a known stance id."""
    if not value:
        return "conservative"
    key = str(value).strip().lower()
    if key in _STANCE_ALIASES:
        return _STANCE_ALIASES[key]
    raw = str(value).strip()
    if raw in _STANCE_ALIASES:
        return _STANCE_ALIASES[raw]
    return "conservative"


def stance_label_zh(stance: str | None) -> str:
    """Return Chinese label for UI."""
    return STANCE_LABELS_ZH.get(normalize_stance(stance), "保守")


def build_decision_stance_guidance(stance: str | None) -> str:
    """Return Stage-2-only guidance block for the current trading stance."""
    normalized = normalize_stance(stance)
    label = stance_label_zh(normalized)

    common_rules = (
        "通用约束（各档都必须遵守，档位不得放宽）：\n"
        "- 先确定 direction / Always In，只评估顺势 setup；支撑、阻力、EMA、通道边界只是等待区域。\n"
        "- 任何新入场必须有已收盘信号棒；弱信号必须有更晚的已收盘确认棒且 follow_through=true。\n"
        "- 突破依据不完整时等待，不得自动转换为限价单；限价单仅用于确认后的回测/二次入场。\n"
        "- 反转必须同时具备 breakout_failure、已收盘反转确认棒和明确的 2.3 方向重判。\n"
        "- 仍必须完整输出 decision_trace，按 §9–§11、§14 走适用节点，不得伪造 trace。\n"
        "- 节点 10.3 须基于结构 entry/stop/target 做数值判断；止损必须保持在交易假设失效位，RR≥1.0。\n"
        "- **方案连续性**：上一轮计划未失效时，明确 position_action=持有；"
        "新有效订单替换旧计划；仅明确撤销或程序确认失效时取消旧计划。\n"
        "- 完成 10.3 后必须填写 estimated_win_rate 与 reasoning；不下单时 estimated_win_rate=null。\n"
        "- decision 与 trace/terminal 必须一致；10.3=否、terminal=wait/reject 或 §14=是时必须不下单并清空新订单价格。\n"
    )

    if normalized == "conservative":
        profile = (
            "【保守】= 优先最清晰的一类顺势信号。\n"
            "- 次优、模糊或仅到达结构位的 setup 默认继续等待。\n"
            "- 10.3 边际情况从严，trade_confidence<60 时通常不下单。\n"
            "- §14 有疑虑即不下单。\n"
        )
    elif normalized == "balanced":
        profile = (
            "【均衡】= 在确认完整的前提下接受次优但可执行的顺势 setup。\n"
            "- 次优信号仍必须已收盘；弱信号仍必须有确认棒。\n"
            "- 10.3 数学期望为正且结构清晰时可执行，须说明主要瑕疵。\n"
            "- trade_confidence 35–49 时仅在确认链完整时允许下单。\n"
        )
    elif normalized == "aggressive":
        profile = (
            "【激进】= 更主动寻找已经确认的顺势机会。\n"
            "- 可接受较弱但已经由确认棒确认的信号，不得提前到信号出现之前。\n"
            "- 10.3 略偏边际但仍为正时可以执行，并明确风险。\n"
            "- trade_confidence 30–44 时仅在确认链和结构止损完整时允许下单。\n"
        )
    else:
        profile = (
            "【极度激进】= 提高机会筛选频率，但缺少确认时仍必须等待。\n"
            "- 在多空之间优先选择与 direction / Always In 一致的一侧，不得因档位强制猜方向。\n"
            "- 可接受最低 25–40 的 trade_confidence，但必须有已收盘信号、必要确认、完整结构止损和正期望。\n"
            "- 确认链不完整、突破依据缺失、逆势证据不足或 §14 触犯时，必须不下单。\n"
        )

    return (
        f"## 交易倾向（当前：{label} / {normalized}）\n\n"
        f"{common_rules}\n"
        f"{profile}\n"
        "请在 decision.reasoning 与 trade_confidence_reasoning 中体现本档位如何影响最终裁定。"
    )
