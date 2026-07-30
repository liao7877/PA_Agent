"""Risk/reward and estimated win-rate helpers for trading decisions."""
from __future__ import annotations

from typing import Any

import math


def is_long_direction(direction: object) -> bool | None:
    """Return True for long, False for short, None if unknown."""
    text = str(direction or "").strip().lower()
    if not text:
        return None
    if "多" in text or text in ("long", "buy", "bull"):
        return True
    if "空" in text or text in ("short", "sell", "bear"):
        return False
    return None


def compute_risk_reward(
    entry: object,
    take_profit: object,
    stop_loss: object,
    direction: object,
) -> dict[str, float | str] | None:
    """Compute risk/reward distances and reward:risk ratio (盈亏比).

    Returns None when prices are invalid or risk is zero.
    """
    try:
        e = float(entry)
        tp = float(take_profit)
        sl = float(stop_loss)
    except (TypeError, ValueError):
        return None

    long = is_long_direction(direction)
    if long is True:
        risk = e - sl
        reward = tp - e
    elif long is False:
        risk = sl - e
        reward = e - tp
    else:
        if tp > e and sl < e:
            risk = e - sl
            reward = tp - e
        elif tp < e and sl > e:
            risk = sl - e
            reward = e - tp
        else:
            return None

    if risk <= 0 or reward <= 0:
        return None

    ratio = reward / risk
    return {
        "risk": risk,
        "reward": reward,
        "ratio": ratio,
        "ratio_text": f"{ratio:.2f} : 1",
    }


def format_estimated_win_rate(decision: dict[str, Any]) -> str | None:
    """Format model-provided estimated_win_rate (0–100) for display."""
    value = decision.get("estimated_win_rate")
    if value is None or value == "":
        return None
    try:
        pct = max(0, min(100, int(float(str(value).strip()))))
    except (ValueError, TypeError):
        return None
    return f"{pct}%"


def format_estimated_win_rate_reasoning(decision: dict[str, Any]) -> str:
    return str(decision.get("estimated_win_rate_reasoning", "") or "").strip()


# Reward must be at least equal to risk (1:1) for any stance.
MIN_RISK_REWARD_RATIO = 1.0


def min_risk_reward_ratio(decision_stance: str | None = None) -> float:
    """Minimum reward:risk ratio required to place an order (same for all stances)."""
    _ = decision_stance  # kept for call-site compatibility
    return MIN_RISK_REWARD_RATIO


def max_risk_reward_ratio() -> float | None:
    """There is no upper reward:risk cap."""
    return None


def passes_trader_equation(
    win_rate_pct: float,
    risk: float,
    reward: float,
) -> bool:
    """Brooks equation: win_rate × reward > (1 - win_rate) × risk."""
    if risk <= 0 or reward <= 0:
        return False
    p = max(0.0, min(100.0, float(win_rate_pct))) / 100.0
    return p * reward > (1.0 - p) * risk


def _parse_win_rate(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return max(0.0, min(100.0, float(str(value).strip())))
    except (TypeError, ValueError):
        return None


def _latest_closed_bar(kline_frame: Any) -> Any | None:
    """Return K1 (newest closed bar) from a snapshot frame."""
    bars = getattr(kline_frame, "bars", None) if kline_frame is not None else None
    if not bars:
        return None
    for bar in bars:
        if int(getattr(bar, "seq", 0) or 0) == 1 and bool(getattr(bar, "closed", True)):
            return bar
    for bar in bars:
        if bool(getattr(bar, "closed", True)):
            return bar
    return None


def validate_limit_order_k1_freshness(
    decision: dict[str, Any],
    kline_frame: Any,
    *,
    bar_analysis: dict[str, Any] | None = None,
) -> list[str]:
    """Reject stale limit orders that K1 has already traded through."""
    if decision.get("order_type") != "限价单":
        return []

    try:
        entry = float(decision.get("entry_price"))
        sl = float(decision.get("stop_loss_price"))
    except (TypeError, ValueError):
        return []

    bar = _latest_closed_bar(kline_frame)
    if bar is None:
        return []

    from pa_agent.util.price_tick import infer_price_tick_from_frame

    tick = infer_price_tick_from_frame(kline_frame) or 0.0
    k_high = float(bar.high)
    k_low = float(bar.low)
    k_close = float(bar.close)
    long = is_long_direction(decision.get("order_direction"))

    pending_planned = False
    if isinstance(bar_analysis, dict):
        entry_bar = bar_analysis.get("entry_bar")
        if isinstance(entry_bar, dict):
            freshness = str(entry_bar.get("freshness", "") or "").strip().lower()
            strength = str(entry_bar.get("strength", "") or "").strip().lower()
            pending_planned = (
                freshness == "pending"
                or strength == "not_triggered"
                or entry_bar.get("bar") is None
            )

    errors: list[str] = []
    if long is True:
        if pending_planned:
            # Planned buy limit: entry must stay below market close (waiting for dip).
            if k_close < entry - tick:
                errors.append(
                    f"limit long (planned): K1 close {k_close:.6g} is below entry {entry:.6g}; "
                    "reprice entry or 不下单"
                )
        else:
            if k_low <= entry + tick:
                errors.append(
                    f"limit long: K1 low {k_low:.6g} already touched/below entry {entry:.6g}; "
                    "pending buy limit is stale — use 市价单, reprice, or 不下单"
                )
            if k_close < entry - tick:
                errors.append(
                    f"limit long: K1 close {k_close:.6g} is below entry {entry:.6g}; "
                    "do not keep a buy limit above market without repricing"
                )
        if k_low <= sl + tick:
            errors.append(
                f"limit long: K1 low {k_low:.6g} already at/below stop {sl:.6g}; "
                "plan invalid — order_type=不下单"
            )
    elif long is False:
        if pending_planned:
            if k_close > entry + tick:
                errors.append(
                    f"limit short (planned): K1 close {k_close:.6g} is above entry {entry:.6g}; "
                    "reprice entry or 不下单"
                )
        else:
            if k_high >= entry - tick:
                errors.append(
                    f"limit short: K1 high {k_high:.6g} already reached/exceeded entry {entry:.6g}; "
                    "pending sell limit is stale — use 市价单, reprice, or 不下单"
                )
            if k_close > entry + tick:
                errors.append(
                    f"limit short: K1 close {k_close:.6g} is above entry {entry:.6g}; "
                    "do not keep a sell limit below market without repricing"
                )
        if k_high >= sl - tick:
            errors.append(
                f"limit short: K1 high {k_high:.6g} already at/above stop {sl:.6g}; "
                "plan invalid — order_type=不下单"
            )

    return errors


def validate_take_profit_2_geometry(
    decision: dict[str, Any],
) -> list[str]:
    """Ensure TP2 is beyond TP1 in the profit direction (no RR cap on TP2)."""
    entry = decision.get("entry_price")
    tp1 = decision.get("take_profit_price")
    tp2 = decision.get("take_profit_price_2")
    sl = decision.get("stop_loss_price")
    direction = decision.get("order_direction")

    try:
        e = float(entry)
        t1 = float(tp1)
        t2 = float(tp2)
        s = float(sl)
    except (TypeError, ValueError):
        return ["decision.take_profit_price_2: required finite number when placing an order"]

    long = is_long_direction(direction)
    if long is True:
        if not (s < e < t1 < t2):
            return [
                "decision.take_profit_price_2: long plan requires "
                "stop < entry < take_profit_price < take_profit_price_2"
            ]
    elif long is False:
        if not (t2 < t1 < e < s):
            return [
                "decision.take_profit_price_2: short plan requires "
                "take_profit_price_2 < take_profit_price < entry < stop"
            ]
    else:
        if t1 > e and t2 <= t1:
            return [
                "decision.take_profit_price_2: must be above take_profit_price for long geometry"
            ]
        if t1 < e and t2 >= t1:
            return [
                "decision.take_profit_price_2: must be below take_profit_price for short geometry"
            ]

    return []


def _reference_atr(kline_frame: Any) -> float | None:
    """Return a current volatility reference for sanity checks, never for stop generation."""
    indicators = getattr(kline_frame, "indicators", None) if kline_frame is not None else None
    values = getattr(indicators, "atr14", ()) if indicators is not None else ()
    for value in values or ():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number

    ranges: list[float] = []
    for bar in (getattr(kline_frame, "bars", ()) or ())[:14]:
        try:
            width = float(bar.high) - float(bar.low)
        except (TypeError, ValueError, AttributeError):
            continue
        if math.isfinite(width) and width > 0:
            ranges.append(width)
    if not ranges:
        return None
    ranges.sort()
    return ranges[len(ranges) // 2]


def validate_structural_stop_anchor(
    decision: dict[str, Any],
    kline_frame: Any,
    *,
    min_atr_fraction: float = 0.10,
) -> list[str]:
    """Require the stop beyond a frame-verified structural anchor plus noise."""
    if decision.get("order_type") not in ("限价单", "突破单", "市价单"):
        return []
    anchor = decision.get("stop_anchor")
    if not isinstance(anchor, dict) or anchor.get("verified") is not True:
        return ["decision.stop_anchor: verified structural stop_anchor is required"]

    source_bar = anchor.get("bar")
    extreme = str(anchor.get("extreme") or "").strip().lower()
    try:
        claimed = float(anchor.get("anchor_price"))
    except (TypeError, ValueError):
        return ["decision.stop_anchor.anchor_price: numeric anchor price is required"]

    if not source_bar:
        return [
            "decision.stop_anchor: a frame-verifiable anchor bar is required; "
            "model-supplied anchor_price alone is not structural evidence"
        ]
    if source_bar:
        from pa_agent.util.price_tick import bar_by_seq, parse_k_seq

        seq = parse_k_seq(source_bar)
        bar = bar_by_seq(kline_frame, seq) if seq is not None else None
        if bar is None or extreme not in ("high", "low"):
            return ["decision.stop_anchor: cited anchor bar/extreme is not verifiable"]
        objective = float(getattr(bar, extreme))
        if abs(objective - claimed) > 1e-9:
            return [
                f"decision.stop_anchor.anchor price {claimed:.6g} does not match "
                f"objective {source_bar}.{extreme}={objective:.6g}"
            ]

    atr = _reference_atr(kline_frame)
    if atr is None:
        return ["decision.stop_anchor: ATR unavailable; cannot verify structural noise buffer"]
    from pa_agent.util.price_tick import infer_price_tick_from_frame

    tick = float(infer_price_tick_from_frame(kline_frame) or 0.0)
    noise = max(tick * 2.0, atr * max(0.0, min_atr_fraction))
    try:
        stop = float(decision.get("stop_loss_price"))
    except (TypeError, ValueError):
        return ["decision.stop_loss_price: numeric stop is required"]

    long = is_long_direction(decision.get("order_direction"))
    if long is True and stop > objective - noise + 1e-12:
        return [
            f"decision.stop_loss_price: stop {stop:.6g} is inside structural anchor "
            f"{objective:.6g} minus noise floor {noise:.6g}"
        ]
    if long is False and stop < objective + noise - 1e-12:
        return [
            f"decision.stop_loss_price: stop {stop:.6g} is inside structural anchor "
            f"{objective:.6g} plus noise floor {noise:.6g}"
        ]
    if long is None:
        return ["decision.order_direction: required for structural anchor validation"]
    return []


def validate_structural_stop_sanity(
    decision: dict[str, Any],
    kline_frame: Any,
    *,
    min_atr_fraction: float = 0.10,
) -> list[str]:
    """Reject only stops that are implausibly tighter than current market noise.

    ATR is a conservative sanity check here. It never chooses, widens, or tightens
    the stop; the model must still place the stop at the price-action invalidation.
    """
    if decision.get("order_type") not in ("限价单", "突破单", "市价单"):
        return []
    rr = compute_risk_reward(
        decision.get("entry_price"),
        decision.get("take_profit_price"),
        decision.get("stop_loss_price"),
        decision.get("order_direction"),
    )
    if rr is None:
        return []
    atr = _reference_atr(kline_frame)
    if atr is None:
        return []

    risk = float(rr["risk"])
    minimum_noise_distance = atr * max(0.0, float(min_atr_fraction))
    tick_candidates: list[float] = []
    try:
        from pa_agent.util.price_tick import infer_price_tick_from_frame

        frame_tick = float(infer_price_tick_from_frame(kline_frame) or 0.0)
        if frame_tick > 0:
            tick_candidates.append(frame_tick)
    except (TypeError, ValueError):
        pass

    # A snapshot whose OHLC values all happen to be integers can make the frame-only
    # precision guess return 1.0 even when the instrument trades in 0.1/0.01 ticks.
    # Price fields provide a conservative finer-precision fallback; ATR remains the
    # primary floor, so an over-precise model quote cannot weaken the noise check.
    price_decimals = 0
    for field in ("entry_price", "stop_loss_price", "take_profit_price", "take_profit_price_2"):
        try:
            text = f"{float(decision.get(field)):.12f}".rstrip("0")
        except (TypeError, ValueError):
            continue
        if "." in text:
            price_decimals = max(price_decimals, len(text.split(".", 1)[1]))
    if price_decimals > 0:
        tick_candidates.append(10 ** (-min(price_decimals, 6)))

    tick = min(tick_candidates) if tick_candidates else 0.0
    minimum_noise_distance = max(minimum_noise_distance, tick * 2.0)

    if risk + 1e-12 < minimum_noise_distance:
        return [
            f"decision.stop_loss_price: risk distance {risk:.6g} is implausibly narrow "
            f"versus current noise (ATR≈{atr:.6g}, sanity floor≈{minimum_noise_distance:.6g}); "
            "recompute the stop from the full pullback/swing/retest invalidation or do not trade"
        ]
    return []


def validate_order_trade_metrics(
    decision: dict[str, Any],
    *,
    decision_stance: str | None = None,
    kline_frame: Any = None,
    bar_analysis: dict[str, Any] | None = None,
    apply_rr_cap_adjustment: bool = False,
) -> list[str]:
    """Validate entry/TP/SL geometry, RR floor, and trader equation for live orders."""
    order_type = decision.get("order_type")
    if order_type not in ("限价单", "突破单", "市价单"):
        return []

    entry = decision.get("entry_price")
    tp = decision.get("take_profit_price")
    sl = decision.get("stop_loss_price")
    direction = decision.get("order_direction")
    rr = compute_risk_reward(entry, tp, sl, direction)
    if rr is None:
        return [
            "decision prices: entry/stop/target must form a valid long (sl<entry<tp) "
            "or short (tp<entry<sl) trade with positive risk and reward"
        ]

    errors: list[str] = []
    ratio = float(rr["ratio"])
    risk = float(rr["risk"])
    reward = float(rr["reward"])
    min_rr = min_risk_reward_ratio(decision_stance)

    if ratio < min_rr:
        errors.append(
            f"decision prices: risk_reward {rr['ratio_text']} is below minimum "
            f"{min_rr:.2f}:1 for this stance; adjust take_profit/stop_loss or set "
            "order_type=不下单 with 10.3=否"
        )

    win_rate = _parse_win_rate(decision.get("estimated_win_rate"))
    if win_rate is None:
        errors.append(
            "decision.estimated_win_rate: required integer 0–100 when placing an order"
        )
    elif not passes_trader_equation(win_rate, risk, reward):
        ev = win_rate / 100.0 * reward - (1.0 - win_rate / 100.0) * risk
        errors.append(
            f"decision prices: trader equation fails at {win_rate:.0f}% win rate "
            f"(risk={risk:.4g}, reward={reward:.4g}, expectancy≈{ev:.4g}); "
            "10.3 must be 否 and order_type=不下单 unless prices are fixed"
        )

    if kline_frame is not None:
        errors.extend(validate_structural_stop_anchor(decision, kline_frame))
        errors.extend(validate_structural_stop_sanity(decision, kline_frame))
        errors.extend(
            validate_limit_order_k1_freshness(
                decision, kline_frame, bar_analysis=bar_analysis
            )
        )

    errors.extend(validate_take_profit_2_geometry(decision))

    return errors
