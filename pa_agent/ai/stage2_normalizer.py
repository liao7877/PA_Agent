"""Normalize common Stage 2 AI JSON variants before schema validation."""
from __future__ import annotations

import copy
import logging
from typing import Any

from pa_agent.ai.trace_normalize import normalize_stage2_traces
from pa_agent.positions.decision_fields import has_position_management_intent
from pa_agent.util.price_tick import (
    normalize_breakout_basis_extreme,
    normalize_breakout_entry_price,
    parse_k_seq,
)

logger = logging.getLogger(__name__)

_TRADE_ORDER_TYPES = frozenset({"限价单", "突破单", "市价单"})
_DIRECTION_TO_ORDER = {
    "bullish": "做多",
    "bearish": "做空",
    "long": "做多",
    "short": "做空",
}
_NO_ORDER_PRICE_FIELDS = (
    "order_direction",
    "entry_price",
    "take_profit_price",
    "stop_loss_price",
    "entry_basis_bar",
    "entry_basis_extreme",
    "entry_rule",
)


def _trace_node_answer(trace: Any, node_id: str) -> str | None:
    if not isinstance(trace, list):
        return None
    for item in trace:
        if not isinstance(item, dict):
            continue
        if str(item.get("node_id", "")).strip() == node_id:
            return str(item.get("answer", "") or "").strip()
    return None


def _section14_violated(trace: Any) -> bool:
    """Return True only when §14 answer is 是 AND the reason text confirms a violation.

    Background: §14 question is "是否触犯禁止行为清单？"
      answer=是  → violated (程序强制 order_type=不下单)
      answer=否  → not violated (can proceed)

    Some models incorrectly write answer=是 to mean "I completed the scan (no violations)".
    To guard against this common mistake we cross-check the reason text: if it contains
    explicit denial phrases (未触犯 / 未违反 / 无触犯 / 通过) we do NOT treat it as a
    violation.  This is a safety hatch — the prompt now clearly specifies answer=否 for
    the no-violation case, so future outputs should be correct.
    """
    _DENIAL_PHRASES = ("未触犯", "未违反", "无触犯", "无违规", "通过扫描", "扫描通过", "无禁止", "未触发")
    if not isinstance(trace, list):
        return False
    for item in trace:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("node_id", "")).strip()
        if not nid.startswith("14"):
            continue
        if str(item.get("answer", "")).strip() != "是":
            continue
        # answer=是: check reason for denial phrases before treating as violation
        reason = str(item.get("reason", "") or "")
        if any(phrase in reason for phrase in _DENIAL_PHRASES):
            # AI wrote answer=是 but reason says no violation — ignore (AI used wrong answer)
            logger.debug(
                "_section14_violated: node %s answer=是 but reason contains denial phrase; "
                "treating as NOT violated (AI should use answer=否 for no-violation)",
                nid,
            )
            continue
        return True
    return False


def _clear_decision_to_no_order(decision: dict[str, Any]) -> None:
    decision["order_type"] = "不下单"
    if decision.get("position_action") == "调整":
        for field in (
            "entry_price",
            "entry_basis_bar",
            "entry_basis_extreme",
            "entry_rule",
        ):
            decision[field] = None
    else:
        for field in _NO_ORDER_PRICE_FIELDS:
            decision[field] = None
    decision["estimated_win_rate"] = None


def _apply_no_order_field_clearing(decision: dict[str, Any]) -> None:
    """Enforce 不下单 price-field rules while preserving position management."""
    if decision.get("position_action") == "调整":
        for field in (
            "entry_price",
            "entry_basis_bar",
            "entry_basis_extreme",
            "entry_rule",
        ):
            decision[field] = None
        decision["estimated_win_rate"] = None
        return
    for field in _NO_ORDER_PRICE_FIELDS:
        decision[field] = None
    decision["estimated_win_rate"] = None


def _set_trace_node_answer(
    trace: Any,
    node_id: str,
    answer: str,
    *,
    reason_suffix: str = "",
) -> None:
    if not isinstance(trace, list):
        return
    for item in trace:
        if not isinstance(item, dict):
            continue
        if str(item.get("node_id", "")).strip() != node_id:
            continue
        item["answer"] = answer
        if reason_suffix:
            base = str(item.get("reason", "") or "").strip()
            item["reason"] = f"{base}{reason_suffix}".strip()
        return


def _coerce_decision_no_order(out: dict[str, Any]) -> bool:
    """When trace/terminal reject a trade, clear decision prices (common model slip)."""
    decision = out.get("decision")
    if not isinstance(decision, dict):
        return False
    if decision.get("order_type") not in _TRADE_ORDER_TYPES:
        return False
    if has_position_management_intent(decision):
        return False

    trace = out.get("decision_trace")
    terminal = out.get("terminal")
    outcome = (
        str(terminal.get("outcome", "")).strip()
        if isinstance(terminal, dict)
        else ""
    )

    triggers: list[str] = []
    if _trace_node_answer(trace, "10.3") == "否":
        triggers.append("10.3=否")
    if outcome in ("wait", "reject"):
        triggers.append(f"terminal.outcome={outcome}")
    if _section14_violated(trace):
        triggers.append("§14触犯")

    if not triggers:
        return False

    _clear_decision_to_no_order(decision)
    logger.debug("Coerced decision to 不下单 (%s)", ", ".join(triggers))
    return True


def _resolve_last_closed_bar_label(
    bar_analysis: dict[str, Any],
    *,
    kline_frame: Any = None,
) -> str | None:
    """Best-effort K{n} label for the most recent closed bar."""
    lcb = bar_analysis.get("last_closed_bar")
    seq = parse_k_seq(lcb) if lcb is not None else None
    if seq is None and kline_frame is not None:
        seq = _max_bar_seq_from_frame(kline_frame)
    if seq is None:
        return None
    return f"K{seq}"


def _ground_market_order_entry_bar(
    bar_analysis: dict[str, Any],
    decision: dict[str, Any],
    *,
    kline_frame: Any = None,
) -> bool:
    """Market orders enter on the latest closed bar; models often reuse pending limit semantics."""
    if decision.get("order_type") != "市价单":
        return False

    entry_bar = bar_analysis.get("entry_bar")
    if not isinstance(entry_bar, dict):
        entry_bar = {}
        bar_analysis["entry_bar"] = entry_bar

    strength = str(entry_bar.get("strength", "") or "").strip().lower()
    freshness = str(entry_bar.get("freshness", "") or "").strip().lower()

    entry_seq = parse_k_seq(entry_bar.get("bar"))
    pending = (
        entry_seq is None
        or strength == "not_triggered"
        or freshness in ("pending", "")
    )
    if not pending:
        return False

    label = _resolve_last_closed_bar_label(bar_analysis, kline_frame=kline_frame)
    if label is None:
        label = "K1"

    entry_bar["bar"] = label
    if strength in ("", "not_triggered", "weak"):
        entry_bar["strength"] = "strong"
    if freshness in ("", "pending", "stale", "invalid"):
        entry_bar["freshness"] = "fresh"
    entry_bar.setdefault("still_valid", True)
    if entry_bar.get("follow_through") in (None, "", False):
        entry_bar["follow_through"] = "pending"
    logger.info("Grounded market order entry_bar.bar -> %s", label)
    return True


def _normalize_signal_entry_bar_chain(bar_analysis: dict[str, Any], decision: dict[str, Any]) -> bool:
    """Signal K must be strictly older than entry K (larger seq); pending entry exempt."""
    if decision.get("order_type") not in _TRADE_ORDER_TYPES:
        return False
    signal_bar = bar_analysis.get("signal_bar")
    entry_bar = bar_analysis.get("entry_bar")
    if not isinstance(signal_bar, dict) or not isinstance(entry_bar, dict):
        return False

    strength = str(entry_bar.get("strength", "") or "").strip().lower()
    freshness = str(entry_bar.get("freshness", "") or "").strip().lower()
    pending = (
        strength == "not_triggered"
        or not entry_bar.get("bar")
        or freshness in ("pending", "stale", "invalid")
    )
    if pending:
        entry_bar["bar"] = None
        entry_bar["strength"] = "not_triggered"
        entry_bar.setdefault("freshness", "pending")
        if entry_bar.get("follow_through") in (None, "", False):
            entry_bar["follow_through"] = "pending"
        return False

    signal_seq = parse_k_seq(signal_bar.get("bar"))
    entry_seq = parse_k_seq(entry_bar.get("bar"))
    if signal_seq is None or entry_seq is None:
        return False
    if signal_seq > entry_seq:
        return False

    signal_bar["bar"] = f"K{entry_seq + 1}"
    logger.debug(
        "signal_bar K%s -> K%s (must be older than entry K%s)",
        signal_seq,
        entry_seq + 1,
        entry_seq,
    )
    return True


def _coerce_decision_when_trade_metrics_fail(
    out: dict[str, Any],
    *,
    decision_stance: str | None = None,
) -> bool:
    """After breakout entry snap, reject orders that still fail RR / trader equation."""
    decision = out.get("decision")
    if not isinstance(decision, dict) or decision.get("order_type") not in _TRADE_ORDER_TYPES:
        return False
    if has_position_management_intent(decision):
        return False
    if decision.get("entry_price") is None:
        return False

    from pa_agent.util.trade_metrics import validate_order_trade_metrics

    metric_errors = validate_order_trade_metrics(
        decision, decision_stance=decision_stance
    )
    if not metric_errors:
        return False

    summary = metric_errors[0]
    _clear_decision_to_no_order(decision)
    _set_trace_node_answer(
        out.get("decision_trace"),
        "10.3",
        "否",
        reason_suffix=f"（程序按 decision 三价校验未通过：{summary}，已改为不下单。）",
    )
    terminal = out.get("terminal")
    if isinstance(terminal, dict):
        terminal["outcome"] = "reject"
        terminal["node_id"] = "10.3"
        terminal.setdefault(
            "label",
            "交易者方程/盈亏比未达标，不下单",
        )
    logger.debug("Coerced decision to 不下单 (trade metrics: %s)", summary)
    return True


def _hoist_probability_alias(prediction: dict[str, Any], *, field: str = "probabilities") -> None:
    """Models often write singular ``probability`` instead of ``probabilities``."""
    if prediction.get(field) is not None:
        return
    alias = prediction.get("probability")
    if isinstance(alias, dict):
        prediction[field] = alias
        prediction.pop("probability", None)
        logger.info("Mapped next_*_prediction probability -> %s", field)


def _normalize_next_cycle_prediction(prediction: dict[str, Any]) -> None:
    """In-place normalize next_cycle_prediction common model quirks. Idempotent."""
    from pa_agent.ai.cycle_enums import CYCLE_ORDER

    if not isinstance(prediction, dict):
        return

    _hoist_probability_alias(prediction)

    # 1. unpredictable fallback
    unpredictable = bool(prediction.get("unpredictable", False))
    prediction["unpredictable"] = unpredictable

    # 2. features_used: ensure list, dedup, minimum set
    feats = prediction.get("features_used")
    if not isinstance(feats, list):
        feats = []
    feats = [f for f in feats if isinstance(f, str)]
    if "stage1_diagnosis" not in feats:
        feats.insert(0, "stage1_diagnosis")
    seen: set[str] = set()
    deduped: list[str] = []
    for f in feats:
        if f not in seen:
            deduped.append(f)
            seen.add(f)
    prediction["features_used"] = deduped

    # 3. reasoning truncation
    reasoning = prediction.get("reasoning")
    if isinstance(reasoning, str) and len(reasoning) > 1500:
        prediction["reasoning"] = reasoning[:1499] + "…"
    elif not isinstance(reasoning, str):
        prediction["reasoning"] = ""

    if unpredictable:
        # unpredictable → force cycle / direction / probabilities = null
        prediction["cycle"] = None
        prediction["direction"] = None
        prediction["probabilities"] = None
        return

    # 4. probabilities integer rounding, clamping, and sum normalization
    probs = prediction.get("probabilities")
    if isinstance(probs, dict):
        normalized: dict[str, int] = {}
        for key in CYCLE_ORDER:
            raw = probs.get(key)
            try:
                value = int(round(float(raw))) if raw is not None else 0
            except (TypeError, ValueError):
                value = 0
            normalized[key] = max(0, min(100, value))

        # Auto-rescale if sum is outside [99, 101] (model arithmetic error)
        total = sum(normalized[k] for k in CYCLE_ORDER)
        if total > 0 and not (99 <= total <= 101):
            scale = 100.0 / total
            rescaled = {k: int(round(normalized[k] * scale)) for k in CYCLE_ORDER}
            # Fix rounding residual so sum == 100
            diff = 100 - sum(rescaled[k] for k in CYCLE_ORDER)
            if diff != 0:
                # Add/subtract from the largest bucket
                biggest = max(CYCLE_ORDER, key=lambda k: rescaled[k])
                rescaled[biggest] = max(0, rescaled[biggest] + diff)
            normalized = rescaled
            logger.debug(
                "next_cycle_prediction probabilities rescaled (sum was %d -> 100)", total
            )

        prediction["probabilities"] = normalized

        # 5. cycle = argmax, tie-break by CYCLE_ORDER literal order
        max_value = max(normalized[k] for k in CYCLE_ORDER)
        # First winner in CYCLE_ORDER order
        argmax_cycle = next(k for k in CYCLE_ORDER if normalized[k] == max_value)

        model_cycle = str(prediction.get("cycle") or "").strip().lower()
        if model_cycle != argmax_cycle:
            logger.debug(
                "next_cycle_prediction cycle %r -> %r (argmax of %s)",
                model_cycle, argmax_cycle, normalized,
            )
            prediction["cycle"] = argmax_cycle

    # direction: keep model value; only type-coerce non-string to None
    direction = prediction.get("direction")
    if direction is not None and not isinstance(direction, str):
        prediction["direction"] = None


def _normalize_next_bar_prediction(prediction: dict[str, Any]) -> None:
    """In-place normalize next_bar_prediction common model quirks. Idempotent."""
    if not isinstance(prediction, dict):
        return

    _hoist_probability_alias(prediction)

    # 1. unpredictable fallback
    unpredictable = bool(prediction.get("unpredictable", False))
    prediction["unpredictable"] = unpredictable

    # 2. features_used: ensure list, dedup, minimum set
    feats = prediction.get("features_used")
    if not isinstance(feats, list):
        feats = []
    feats = [f for f in feats if isinstance(f, str)]
    if "stage1_diagnosis" not in feats:
        feats.insert(0, "stage1_diagnosis")
    seen: set[str] = set()
    deduped: list[str] = []
    for f in feats:
        if f not in seen:
            deduped.append(f)
            seen.add(f)
    prediction["features_used"] = deduped

    # 3. reasoning truncation (R7.6)
    reasoning = prediction.get("reasoning")
    if isinstance(reasoning, str) and len(reasoning) > 1500:
        prediction["reasoning"] = reasoning[:1499] + "…"
    elif not isinstance(reasoning, str):
        prediction["reasoning"] = ""

    if unpredictable:
        # unpredictable → force direction / probabilities = null
        prediction["direction"] = None
        prediction["probabilities"] = None
        return

    # 4. probabilities integer rounding (R3.1)
    probs = prediction.get("probabilities")
    if isinstance(probs, dict):
        normalized: dict[str, int] = {}
        bar_order = ("bullish", "bearish", "neutral")
        for key in bar_order:
            raw = probs.get(key)
            try:
                value = int(round(float(raw))) if raw is not None else 0
            except (TypeError, ValueError):
                value = 0
            normalized[key] = max(0, min(100, value))

        # Auto-rescale if sum is outside [99, 101] (model arithmetic error)
        total = sum(normalized[k] for k in bar_order)
        if total > 0 and not (99 <= total <= 101):
            scale = 100.0 / total
            rescaled = {k: int(round(normalized[k] * scale)) for k in bar_order}
            diff = 100 - sum(rescaled[k] for k in bar_order)
            if diff != 0:
                biggest = max(bar_order, key=lambda k: rescaled[k])
                rescaled[biggest] = max(0, rescaled[biggest] + diff)
            normalized = rescaled
            logger.debug(
                "next_bar_prediction probabilities rescaled (sum was %d -> 100)", total
            )

        prediction["probabilities"] = normalized

        # 5. direction = argmax (R3.3) — respect model choice on ties
        order = ("bullish", "bearish", "neutral")
        max_value = max(normalized[k] for k in order)
        tied_winners = [k for k in order if normalized[k] == max_value]
        model_direction = str(prediction.get("direction") or "").strip().lower()

        if len(tied_winners) > 1:
            # Tie: preserve model's choice if it's one of the winners
            if model_direction in tied_winners:
                pass  # keep model's semantic choice
            else:
                # Model direction not in tied set — override with first winner
                logger.warning(
                    "next_bar_prediction direction=%r not in tied winners %s "
                    "(probs=%s); overriding to %r",
                    model_direction, tied_winners, normalized, tied_winners[0],
                )
                prediction["direction"] = tied_winners[0]
        else:
            # Clear winner
            expected = tied_winners[0]
            if model_direction != expected:
                logger.debug(
                    "next_bar_prediction direction %r -> %r (argmax of %s)",
                    model_direction, expected, normalized,
                )
                prediction["direction"] = expected
            # else: model direction matches argmax, no change needed
    # else: unparseable probabilities with unpredictable=False — leave for validator


def _infer_order_direction(
    decision: dict[str, Any],
    out: dict[str, Any],
    *,
    stage1_json: dict[str, Any] | None = None,
) -> bool:
    """Fill missing order_direction from diagnosis / stage1 / price geometry."""
    current = decision.get("order_direction")
    if isinstance(current, str) and current.strip():
        return False

    order_type = decision.get("order_type")
    needs_direction = order_type in _TRADE_ORDER_TYPES or (
        order_type == "不下单" and decision.get("position_action") == "调整"
    )
    if not needs_direction:
        return False

    mapped: str | None = None
    entry = decision.get("entry_price")
    tp = decision.get("take_profit_price")
    sl = decision.get("stop_loss_price")
    if (
        isinstance(entry, (int, float))
        and isinstance(tp, (int, float))
        and isinstance(sl, (int, float))
    ):
        if tp > entry and sl < entry:
            mapped = "做多"
        elif tp < entry and sl > entry:
            mapped = "做空"

    if not mapped:
        extreme = decision.get("entry_basis_extreme")
        if extreme == "high":
            mapped = "做多"
        elif extreme == "low":
            mapped = "做空"

    if not mapped:
        ba = out.get("bar_analysis")
        if isinstance(ba, dict):
            always_in = str(ba.get("always_in", "") or "").strip().lower()
            if always_in == "long":
                mapped = "做多"
            elif always_in == "short":
                mapped = "做空"

    if not mapped:
        for source in (
            out.get("diagnosis_summary")
            if isinstance(out.get("diagnosis_summary"), dict)
            else None,
            stage1_json,
        ):
            if not isinstance(source, dict):
                continue
            key = str(source.get("direction") or "").strip().lower()
            mapped = _DIRECTION_TO_ORDER.get(key)
            if mapped:
                break

    if not mapped and isinstance(entry, (int, float)):
        if isinstance(tp, (int, float)):
            mapped = "做多" if tp > entry else "做空" if tp < entry else None
        if not mapped and isinstance(sl, (int, float)):
            mapped = "做多" if sl < entry else "做空" if sl > entry else None

    if not mapped:
        return False

    decision["order_direction"] = mapped
    logger.info("Inferred order_direction -> %s (order_type=%s)", mapped, order_type)
    return True


def _normalize_estimated_win_rate_reasoning(decision: dict[str, Any]) -> None:
    """Schema requires string reasoning when estimated_win_rate is set for trade orders."""
    order_type = decision.get("order_type")
    if order_type not in _TRADE_ORDER_TYPES:
        return
    rate = decision.get("estimated_win_rate")
    if rate is None:
        return
    reasoning = decision.get("estimated_win_rate_reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        return
    decision["estimated_win_rate_reasoning"] = (
        f"模型未填写胜率依据，程序沿用 estimated_win_rate={rate}% 用于校验。"
    )
    logger.debug("Filled estimated_win_rate_reasoning for trade order")


def _normalize_watch_points(decision: dict[str, Any]) -> None:
    """Coerce watch_points items to strings when the model outputs objects."""
    raw = decision.get("watch_points")
    if not isinstance(raw, list):
        return
    normalized: list[str] = []
    changed = False
    for item in raw:
        if isinstance(item, str):
            normalized.append(item)
            continue
        changed = True
        if isinstance(item, dict):
            parts: list[str] = []
            for key in ("trigger", "condition", "action", "note", "text", "reason"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    parts.append(val.strip())
            normalized.append("；".join(parts) if parts else str(item))
        else:
            normalized.append(str(item))
    if changed:
        logger.info("Normalized watch_points objects -> strings (%s items)", len(normalized))
        decision["watch_points"] = normalized


def _max_bar_seq_from_frame(kline_frame: Any) -> int | None:
    bars = getattr(kline_frame, "bars", None) if kline_frame is not None else None
    if not bars:
        return None
    seqs = [int(getattr(b, "seq", 0)) for b in bars if getattr(b, "seq", None)]
    return max(seqs) if seqs else None


def normalize_stage2(
    obj: dict[str, Any],
    *,
    normalization_mode: str = "strict",
    kline_frame: Any = None,
    decision_stance: str | None = None,
    stage1_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of *obj* with decision_trace quirks corrected."""
    out = copy.deepcopy(obj)
    frame_max = _max_bar_seq_from_frame(kline_frame)
    _coerce_decision_no_order(out)
    decision = out.get("decision")
    if isinstance(decision, dict) and normalize_breakout_basis_extreme(decision):
        logger.debug(
            "breakout entry_basis_extreme aligned to %s for %s",
            decision.get("entry_basis_extreme"),
            decision.get("order_direction"),
        )
    if isinstance(decision, dict) and normalize_breakout_entry_price(
        decision, kline_frame=kline_frame
    ):
        logger.debug(
            "breakout entry_price adjusted to basis extreme ± 1 tick (basis=%s)",
            decision.get("entry_basis_bar"),
        )
    _coerce_decision_when_trade_metrics_fail(out, decision_stance=decision_stance)

    decision = out.get("decision")
    if isinstance(decision, dict):
        _infer_order_direction(decision, out, stage1_json=stage1_json)

    # ── DecisionNodeEngine: fill §9.1/§9.2/§9.3/§9.5/§11 ─────────────────────
    if kline_frame is not None:
        try:
            from pa_agent.ai.decision_nodes import DecisionNodeEngine
            DecisionNodeEngine.apply_stage2(out, kline_frame, stage1_json)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DecisionNodeEngine.apply_stage2 failed: %s", exc)

    normalize_stage2_traces(
        out,
        normalization_mode=normalization_mode,
        default_max_seq=frame_max,
    )
    decision = out.get("decision")
    if isinstance(decision, dict):
        _normalize_watch_points(decision)
        _normalize_estimated_win_rate_reasoning(decision)
    if isinstance(decision, dict) and decision.get("order_type") == "不下单":
        _apply_no_order_field_clearing(decision)

    bar_analysis = out.get("bar_analysis")
    decision = out.get("decision")
    if isinstance(bar_analysis, dict) and isinstance(decision, dict):
        _ground_market_order_entry_bar(
            bar_analysis, decision, kline_frame=kline_frame
        )
        if _normalize_signal_entry_bar_chain(bar_analysis, decision):
            pass
    if isinstance(bar_analysis, dict):
        signal_bar = bar_analysis.get("signal_bar")
        if isinstance(signal_bar, dict) and not signal_bar.get("bar"):
            signal_bar["bar"] = None
            signal_bar.setdefault("quality", "invalid")
            signal_bar.setdefault("pattern", "none")

        entry_bar = bar_analysis.get("entry_bar")
        order_type = decision.get("order_type") if isinstance(decision, dict) else None
        if isinstance(entry_bar, dict):
            strength = str(entry_bar.get("strength", "") or "").strip().lower()
            has_bar = bool(entry_bar.get("bar"))
            if (
                order_type != "市价单"
                and (strength == "not_triggered" or not has_bar)
            ):
                # Pending limit/breakout orders do not have an actual entry bar
                # yet. Normalize common model variants before schema checks.
                entry_bar["strength"] = "not_triggered"
                entry_bar.setdefault("bar", None)
                entry_bar.setdefault("freshness", "pending")
                if entry_bar.get("follow_through") in (None, "", "pending"):
                    entry_bar["follow_through"] = "pending"

    # Next bar prediction normalization (R8.6: only when field exists)
    pred = out.get("next_bar_prediction")
    if isinstance(pred, dict):
        _normalize_next_bar_prediction(pred)

    # Next cycle prediction normalization (only when field exists)
    pred_c = out.get("next_cycle_prediction")
    if isinstance(pred_c, dict):
        _normalize_next_cycle_prediction(pred_c)

    return out
