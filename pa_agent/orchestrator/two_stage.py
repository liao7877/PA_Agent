"""Two-stage AI analysis orchestrator.

Coordinates the full Stage 1 (diagnosis) → Stage 2 (decision) pipeline:
  1. Build Stage 1 prompt via PromptAssembler
  2. Call DeepSeekClient
  3. Validate Stage 1 JSON
  4. Route strategy files
  5. Load experience entries
  6. Build Stage 2 prompt
  7. Call DeepSeekClient
  8. Validate Stage 2 JSON
  9. Persist full record

Cancel checks are performed before each stage and after each API call.
Network/timeout errors are caught and recorded on the partial record.

On validation failure, ``validation_retry`` may append a feedback user turn and
re-call the API (see ``ValidationSettings.retry_*``). Semantic / safety errors
are not retried; immutable-field cheat detection rejects suspicious retries.
"""
from __future__ import annotations

# Legacy flag kept for tests/docs; retry is governed by ValidationSettings.
STAGE2_VALIDATION_AUTO_RETRY = False

import copy
import dataclasses
import inspect
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from pa_agent.ai.deepseek_client import DeepSeekClient
    from pa_agent.ai.json_validator import JsonValidator
    from pa_agent.ai.prompt_assembler import PromptAssembler
    from pa_agent.config.settings import Settings
    from pa_agent.records.experience_reader import ExperienceReader
    from pa_agent.records.pending_writer import PendingWriter

from pa_agent.ai.json_validator import Ok, ValidationError, resolve_stage_json_text, _strip_fences
from pa_agent.orchestrator.validation_retry import validate_with_retry
from pa_agent.data.base import KlineFrame
from pa_agent.records.schema import AnalysisRecord, RecordMeta
from pa_agent.util.threading import CancelToken, OrchestratorEvent
from pa_agent.util.timefmt import now_local_ms

logger = logging.getLogger(__name__)


def _latency_ms_label(latency_ms: object) -> str:
    """Format API latency for console logs; tolerate mocks or missing values."""
    try:
        return f"{float(latency_ms):.0f}ms"
    except (TypeError, ValueError):
        return "?"

# When the gateway buffers the full reply, emit pseudo-stream chunks to the UI.
_FALLBACK_STREAM_CHUNK = 48


def _json_unclosed_depth(text: str) -> int:
    stripped = (text or "").strip()
    if not stripped.startswith("{"):
        return 0
    depth = 0
    in_string = False
    escape = False
    for ch in stripped:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth


def _looks_like_truncated_json(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped.startswith("{"):
        return False
    try:
        json.loads(stripped)
        return False
    except json.JSONDecodeError:
        depth = _json_unclosed_depth(stripped)
        return depth > 0 or not stripped.rstrip().endswith("}")


def _json_truncation_hint(content: str, err: ValidationError) -> str | None:
    """Detect incomplete JSON (stream stopped mid-object) vs a stray syntax typo."""
    if err.category != "a":
        return None
    stripped = (content or "").strip()
    if not stripped.startswith("{"):
        return None
    depth = 0
    in_string = False
    escape = False
    for ch in stripped:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    if depth > 0 or not stripped.rstrip().endswith("}"):
        return (
            f"阶段 JSON 正文约 {len(stripped)} 字符，在输出过程中被截断"
            f"（未闭合对象约 {max(depth, 1)} 层，解析位置 {err.parse_position}）。"
            " 常见原因：completion 额度主要在思考区用尽，正文 JSON 只写了一小段。"
        )
    return None


def _enrich_stage2_validation_message(err: ValidationError, reply: Any) -> str:
    """Add actionable context for empty content or truncated JSON."""
    from pa_agent.ai.provider_errors import (
        PROVIDER_QUOTA_USER_MESSAGE,
        is_provider_quota_exhausted,
    )

    if err.category == "e" or is_provider_quota_exhausted(err.raw_text):
        return err.message or PROVIDER_QUOTA_USER_MESSAGE
    from pa_agent.ai.validation_messages import format_validation_errors

    detail = format_validation_errors(
        err.invalid_fields, missing_fields=err.missing_fields
    )
    content = (getattr(reply, "content", None) or "").strip()
    trunc = _json_truncation_hint(content, err)
    if trunc:
        usage = getattr(reply, "usage", None)
        completion = getattr(usage, "completion_tokens", 0) if usage else 0
        reasoning_len = len(getattr(reply, "reasoning_content", None) or "")
        msg = f"{err.message}。{trunc} completion_tokens≈{completion}，思考区约 {reasoning_len} 字。"
        return f"{msg}。{detail}" if detail else msg
    if err.category != "d" or (err.raw_text or "").strip():
        return f"{err.message}。{detail}" if detail else err.message
    if content:
        return f"{err.message}。{detail}" if detail else err.message
    reasoning = getattr(reply, "reasoning_content", None) or ""
    usage = getattr(reply, "usage", None)
    completion = getattr(usage, "completion_tokens", 0) if usage else 0
    if reasoning and "{" not in reasoning:
        return (
            f"{err.message}：扩展思考已输出约 {len(reasoning)} 字，但正文 content 为空，"
            f"且思考中未见 JSON（completion_tokens≈{completion}）。"
            " 常见原因是思考在输出阶段二 JSON 前被截断或网关提前结束流。"
            " 请缩短 prompt、检查 Packy 分组限额，或调整模型/Reasoning Effort 后重新分析。"
        )
    if reasoning:
        return (
            f"{err.message}：正文 content 为空；请把阶段二 JSON 写在 content 正文，"
            "不要只写在思考区。"
        )
    return f"{err.message}。{detail}" if detail else err.message


def _enrich_stage1_validation_message(err: ValidationError, reply: Any) -> str:
    """Add actionable context for empty content or truncated JSON."""
    from pa_agent.ai.provider_errors import (
        PROVIDER_QUOTA_USER_MESSAGE,
        is_provider_quota_exhausted,
    )

    if err.category == "e" or is_provider_quota_exhausted(err.raw_text):
        return err.message or PROVIDER_QUOTA_USER_MESSAGE
    from pa_agent.ai.validation_messages import format_validation_errors

    detail = format_validation_errors(
        err.invalid_fields, missing_fields=err.missing_fields
    )
    content = (getattr(reply, "content", None) or "").strip()
    trunc = _json_truncation_hint(content, err)
    if trunc:
        usage = getattr(reply, "usage", None)
        completion = getattr(usage, "completion_tokens", 0) if usage else 0
        reasoning_len = len(getattr(reply, "reasoning_content", None) or "")
        msg = f"{err.message}。{trunc} completion_tokens≈{completion}，思考区约 {reasoning_len} 字。"
        return f"{msg}。{detail}" if detail else msg
    if err.category != "d" or (err.raw_text or "").strip():
        return f"{err.message}。{detail}" if detail else err.message
    if content:
        return f"{err.message}。{detail}" if detail else err.message
    reasoning = getattr(reply, "reasoning_content", None) or ""
    usage = getattr(reply, "usage", None)
    completion = getattr(usage, "completion_tokens", 0) if usage else 0
    if reasoning and "{" not in reasoning:
        return (
            f"{err.message}：扩展思考已输出约 {len(reasoning)} 字，但正文 content 为空，"
            f"且思考中未见 JSON（completion_tokens≈{completion}）。"
            " 常见原因是思考占满输出额度后被截断。"
            " 请缩短 prompt、检查网关输出上限，或调整 Reasoning Effort 后重新分析。"
        )
    if reasoning:
        return (
            f"{err.message}：正文 content 为空；请把阶段一 JSON 写在 content 正文，"
            "不要只写在思考区。"
        )
    return f"{err.message}。{detail}" if detail else err.message


def _emit_buffered_stream(
    text: str,
    on_token: Callable[[str], None] | None,
    *,
    chunk_size: int = _FALLBACK_STREAM_CHUNK,
) -> bool:
    """Push *text* through *on_token* in slices if the API did not stream deltas."""
    if on_token is None or not text:
        return False
    for i in range(0, len(text), chunk_size):
        on_token(text[i : i + chunk_size])
    return True


def _reply_with_resolved_content(
    reply: Any,
    content: str,
    *,
    raw_note: dict[str, Any] | None = None,
) -> Any:
    raw = dict(reply.raw)
    if raw_note:
        raw.update(raw_note)
    raw["content"] = content
    return dataclasses.replace(reply, content=content, raw=raw)


def _merge_stage_replies(first: Any, second: Any, *, fallback_reason: str) -> Any:
    from pa_agent.ai.deepseek_client import AIUsage

    usage = AIUsage(
        prompt_tokens=first.usage.prompt_tokens + second.usage.prompt_tokens,
        cached_prompt_tokens=first.usage.cached_prompt_tokens
        + second.usage.cached_prompt_tokens,
        completion_tokens=first.usage.completion_tokens + second.usage.completion_tokens,
        total_tokens=first.usage.total_tokens + second.usage.total_tokens,
    )
    raw = dict(second.raw)
    raw.update(
        {
            "empty_content_fallback": True,
            "fallback_reason": fallback_reason,
            "first_attempt_reasoning_chars": len(first.reasoning_content or ""),
            "first_attempt_request_id": first.request_id,
        }
    )
    return dataclasses.replace(
        second,
        reasoning_content=first.reasoning_content or second.reasoning_content,
        usage=usage,
        latency_ms=first.latency_ms + second.latency_ms,
        raw=raw,
    )


def _stream_stage_with_empty_content_fallback(
    client: Any,
    messages: list[dict[str, Any]],
    *,
    stage: str,
    thinking: bool,
    reasoning_effort: str,
    cancel_token: CancelToken | None,
    on_reasoning_token: Callable[[str], None] | None,
    on_content_token: Callable[[str], None] | None,
) -> Any:
    """Call stream_chat; recover JSON from reasoning or retry once without thinking."""
    reply = client.stream_chat(
        messages,
        on_reasoning_token=on_reasoning_token,
        on_content_token=on_content_token,
        cancel_token=cancel_token,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
    )
    resolved = resolve_stage_json_text(reply.content, reply.reasoning_content)
    truncated = bool(resolved.strip()) and _looks_like_truncated_json(resolved)
    if resolved.strip() and not truncated:
        if resolved != (reply.content or "").strip():
            return _reply_with_resolved_content(
                reply,
                resolved,
                raw_note={"json_recovered_from": "reasoning_content"},
            )
        return reply

    if not thinking:
        return reply

    fallback_reason = (
        "truncated_json_after_thinking" if truncated else "empty_content_after_thinking"
    )
    logger.warning(
        "Stage %s: %s (effort=%s); retrying once with thinking disabled",
        stage,
        "truncated JSON after thinking" if truncated else "empty JSON after thinking",
        reasoning_effort,
    )
    retry = client.stream_chat(
        messages,
        on_content_token=on_content_token,
        cancel_token=cancel_token,
        thinking=False,
        reasoning_effort=None,
    )
    retry_resolved = resolve_stage_json_text(retry.content, retry.reasoning_content)
    if retry_resolved.strip() and retry_resolved != (retry.content or "").strip():
        retry = _reply_with_resolved_content(
            retry,
            retry_resolved,
            raw_note={"json_recovered_from": "reasoning_content"},
        )
    return _merge_stage_replies(reply, retry, fallback_reason=fallback_reason)


def _stage2_decision_from_validation_error(
    *,
    content: str,
    kline_frame: KlineFrame,
    decision_stance: str | None,
    stage1_json: dict[str, Any] | None,
    skip_next_bar: bool,
) -> dict[str, Any] | None:
    """Keep stage-2 decision visible when validation fails but JSON is usable."""
    resolved = resolve_stage_json_text(content, None)
    stripped = _strip_fences(resolved)
    if not stripped.startswith("{"):
        return None
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    try:
        from pa_agent.ai.stage2_normalizer import normalize_stage2

        return normalize_stage2(
            obj,
            normalization_mode="lenient",
            kline_frame=kline_frame,
            decision_stance=decision_stance,
            stage1_json=stage1_json,
            skip_next_bar=skip_next_bar,
        )
    except Exception:  # noqa: BLE001
        return obj


def _filter_kwargs(func: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return only kwargs that *func* accepts; tolerant of mocks and **kwargs."""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return dict(kwargs)
    if any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    ):
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k in sig.parameters}


def _compute_market_features_block(frame: KlineFrame) -> str | None:
    """Render the simple market-features block for injection into Stage 2 prompt."""
    try:
        from pa_agent.ai.market_features import (
            compute_simple_market_features,
            render_simple_market_features,
        )

        features = compute_simple_market_features(frame)
        return render_simple_market_features(features)
    except Exception as exc:  # noqa: BLE001
        logger.debug("market_features computation skipped: %s", exc)
        return None


def _inject_market_features_into_stage2_messages(
    messages: list[dict[str, Any]],
    frame: KlineFrame,
) -> list[dict[str, Any]]:
    """Ensure Stage 2 user prompt contains the program market-features block.

    If the assembler already injected the block (upstream behaviour), this is a
    no-op. Otherwise compute the block and insert it before the first anchor
    marker or append it to the end of the user turn.
    """
    try:
        from pa_agent.ai.market_features import (
            MARKET_FEATURES_SECTION_PREFIX,
            inject_market_features_section,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("market_features injection skipped: %s", exc)
        return messages

    block = _compute_market_features_block(frame)
    if not block or not block.strip():
        return messages

    updated = False
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str) or not content:
            continue
        if MARKET_FEATURES_SECTION_PREFIX in content:
            updated = True
            break
    if updated:
        return messages

    for i, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str) or not content:
            continue
        new_content = inject_market_features_section(content, block)
        if new_content != content:
            messages[i] = {**msg, "content": new_content}
            updated = True
            break

    if not updated:
        for i, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            messages[i] = {**msg, "content": content.rstrip() + "\n\n" + block + "\n"}
            break
    return messages


def _apply_continuity_guard_to_stage2(
    stage2_json: dict[str, Any],
    *,
    frame: KlineFrame,
    stage1_json: dict[str, Any],
    previous_record: AnalysisRecord | None,
    cooldown_bars: int,
) -> dict[str, Any]:
    """Apply program continuity guard to a validated Stage 2 decision.

    Mirrors what upstream's stage2_normalizer does internally so the guard still
    runs when the paired normalizer is from main (which lacks the integration).
    """
    try:
        from pa_agent.ai.decision_continuity import (
            apply_continuity_guard,
            build_continuity_context,
        )

        ctx = build_continuity_context(
            frame=frame,
            stage1_json=stage1_json,
            previous_record=previous_record,
            cooldown_bars=cooldown_bars,
        )
        return apply_continuity_guard(stage2_json, ctx)
    except Exception as exc:  # noqa: BLE001
        logger.warning("apply_continuity_guard failed: %s", exc)
        return stage2_json


def _log_kv_prefix_chain_support(provider_settings: Any) -> bool:
    """Log and return whether the provider supports KV prefix-chain for Stage 2."""
    try:
        from pa_agent.ai.deepseek_client import supports_kv_prefix_chain

        supported = supports_kv_prefix_chain(provider_settings)
    except Exception as exc:  # noqa: BLE001
        logger.debug("supports_kv_prefix_chain check skipped: %s", exc)
        return True
    logger.info("Stage 2 KV prefix-chain support: %s", supported)
    return supported


def _build_empty_record(
    frame: KlineFrame,
    settings: Optional["Settings"],
) -> AnalysisRecord:
    """Build a partial AnalysisRecord with meta populated from the frame."""
    ts_ms = now_local_ms()
    ts_iso = datetime.fromtimestamp(ts_ms / 1000).isoformat(timespec="milliseconds")

    # Build masked provider snapshot
    ai_provider: dict[str, Any] = {}
    if settings is not None:
        from pa_agent.util.mask_secret import mask_secret
        p = settings.provider
        ai_provider = {
            "model": p.model,
            "base_url": p.base_url,
            "api_key": mask_secret(p.api_key) if p.api_key else "****",
            "thinking": p.thinking,
            "reasoning_effort": p.reasoning_effort,
            "context_window": p.context_window,
        }

    # Serialize kline bars
    kline_data: list[dict] = []
    for bar in frame.bars:
        if dataclasses.is_dataclass(bar) and not isinstance(bar, type):
            kline_data.append(dataclasses.asdict(bar))
        else:
            kline_data.append(bar.__dict__)

    from pa_agent.ai.decision_stance import normalize_stance

    decision_stance = "conservative"
    if settings is not None:
        decision_stance = normalize_stance(
            getattr(settings.general, "decision_stance", "conservative")
        )

    meta = RecordMeta(
        timestamp_local_iso=ts_iso,
        timestamp_local_ms=ts_ms,
        symbol=frame.symbol,
        timeframe=frame.timeframe,
        bar_count=len(frame.bars),
        ai_provider=ai_provider,
        decision_stance=decision_stance,
    )

    return AnalysisRecord(
        meta=meta,
        kline_data=kline_data,
        htf_text="",
        stage1_messages=[],
        stage1_response=None,
        stage1_diagnosis=None,
        stage2_messages=[],
        stage2_response=None,
        stage2_decision=None,
        strategy_files_used=[],
        experience_loaded=[],
        exception=None,
        usage_total={},
    )


def _accumulate_usage(current: dict, reply_usage: Any) -> dict:
    """Merge an AIUsage object into the running usage_total dict."""
    result = dict(current)
    result["prompt_tokens"] = (
        result.get("prompt_tokens", 0) + getattr(reply_usage, "prompt_tokens", 0)
    )
    result["cached_prompt_tokens"] = (
        result.get("cached_prompt_tokens", 0)
        + getattr(reply_usage, "cached_prompt_tokens", 0)
    )
    result["completion_tokens"] = (
        result.get("completion_tokens", 0) + getattr(reply_usage, "completion_tokens", 0)
    )
    result["total_tokens"] = (
        result.get("total_tokens", 0) + getattr(reply_usage, "total_tokens", 0)
    )
    return result


def _accumulate_usage_calls(current: dict, usage_calls: list[Any]) -> dict:
    total = dict(current)
    for usage in usage_calls:
        if usage is not None:
            total = _accumulate_usage(total, usage)
    return total


class TwoStageOrchestrator:
    """Orchestrates the two-stage AI analysis pipeline.

    Parameters
    ----------
    client:
        DeepSeekClient instance for API calls.
    assembler:
        PromptAssembler for building Stage 1 and Stage 2 message lists.
    router:
        Either the ``route_strategy_files`` function or an object with a
        ``.route()`` method.
    validator:
        JsonValidator for validating Stage 1 and Stage 2 responses.
    pending_writer:
        PendingWriter for persisting full and partial records.
    exp_reader:
        ExperienceReader for loading top-5 experience entries.
    settings:
        Optional Settings object; used for ``ai_provider`` meta and
        ``reasoning_effort`` forwarding.
    """

    def __init__(
        self,
        client: "DeepSeekClient",
        assembler: "PromptAssembler",
        router: Any,
        validator: "JsonValidator",
        pending_writer: "PendingWriter",
        exp_reader: "ExperienceReader",
        settings: Optional["Settings"] = None,
    ) -> None:
        self._client = client
        self._assembler = assembler
        self._router = router
        self._validator = validator
        self._pending_writer = pending_writer
        self._exp_reader = exp_reader
        self._settings = settings

    def _validation_settings(self) -> Any:
        if self._settings is not None and hasattr(self._settings, "validation"):
            return self._settings.validation
        from pa_agent.config.settings import ValidationSettings

        return ValidationSettings()

    # ── Public API ────────────────────────────────────────────────────────────

    def submit(
        self,
        frame: KlineFrame,
        cancel_token: CancelToken,
        on_event: Callable[[OrchestratorEvent], None],
        *,
        on_stage1_reasoning: Callable[[str], None] | None = None,
        on_stage1_content: Callable[[str], None] | None = None,
        on_stage2_reasoning: Callable[[str], None] | None = None,
        on_stage2_content: Callable[[str], None] | None = None,
        on_stage_prompt: Callable[[str, str, str], None] | None = None,
        on_stage2_files: Callable[[list[str]], None] | None = None,
        previous_record: AnalysisRecord | None = None,
        incremental_new_bar_count: int | None = None,
        active_position: Any | None = None,
    ) -> AnalysisRecord:
        """Run the two-stage analysis pipeline and return an AnalysisRecord.

        The ``on_event`` callback is called synchronously at each pipeline
        milestone.  The returned record is always fully populated with
        whatever data was collected before the pipeline terminated (whether
        by success, validation failure, cancellation, or network error).

        Parameters
        ----------
        frame:
            Immutable KlineFrame snapshot to analyse.
        cancel_token:
            Token checked before each stage and after each API call.
        on_event:
            Callback invoked with OrchestratorEvent values.

        Returns
        -------
        AnalysisRecord
            Fully or partially populated record.
        """
        # ── Step 1: Build partial record ──────────────────────────────────────
        record = _build_empty_record(frame, self._settings)

        # ── Step 2: Pre-Stage-1 cancel check ─────────────────────────────────
        if cancel_token.is_set():
            self._pending_writer.save_partial(record, "user_cancelled")
            on_event(OrchestratorEvent.Cancelled)
            return record

        # ── Step 2.5: Preflight data gate (before Stage1Started) ─────────────
        from pa_agent.ai.decision_nodes import check_preflight_data
        pf = check_preflight_data(frame)
        if not pf.ok:
            record = record.model_copy(update={
                "exception": {
                    "type": "insufficient_data",
                    "stage": "preflight",
                    "failed_check": pf.failed_check,
                    "message": pf.reason,
                }
            })
            self._pending_writer.save_partial(record, "insufficient_data")
            on_event(OrchestratorEvent.InsufficientData)
            return record

        # ── Step 3: Stage 1 started ───────────────────────────────────────────
        on_event(OrchestratorEvent.Stage1Started)

        # Resolve analysis mode from settings (default: original)
        analysis_mode = "original"
        if self._settings is not None:
            analysis_mode = str(
                getattr(self._settings.general, "analysis_mode", "original") or "original"
            )

        # ── Step 4: Build Stage 1 messages ───────────────────────────────────
        if previous_record is not None and incremental_new_bar_count is not None:
            incremental_kwargs = _filter_kwargs(
                self._assembler.build_incremental_stage1,
                {
                    "analysis_mode": analysis_mode,
                    "provider_settings": getattr(self._settings, "provider", None),
                    "active_position": active_position,
                },
            )
            messages_s1 = self._assembler.build_incremental_stage1(
                frame,
                previous_record,
                incremental_new_bar_count,
                **incremental_kwargs,
            )
        else:
            stage1_kwargs = _filter_kwargs(
                self._assembler.build_stage1,
                {
                    "analysis_mode": analysis_mode,
                    "active_position": active_position,
                },
            )
            messages_s1 = self._assembler.build_stage1(frame, **stage1_kwargs)

        # ── Step 5: Call AI for Stage 1 ───────────────────────────────────────
        logger.debug("\n" + "="*80)
        logger.debug("【Stage 1 发送的完整 Prompt】")
        logger.debug("="*80)
        for msg in messages_s1:
            role = msg.get("role", "?").upper()
            content = msg.get("content", "")
            logger.debug("\n--- [%s] ---\n%s", role, content)
        logger.debug("="*80 + "\n")

        # Notify conversation tab of the prompt being sent
        if on_stage_prompt is not None:
            s1_system = next((m.get("content", "") for m in messages_s1 if m.get("role") == "system"), "")
            s1_user = next((m.get("content", "") for m in messages_s1 if m.get("role") == "user"), "")
            on_stage_prompt("stage1", s1_system, s1_user)

        _thinking, _effort = self._thinking_params()
        s1_streamed_reasoning = False
        s1_streamed_content = False

        def _on_s1_reasoning(chunk: str) -> None:
            nonlocal s1_streamed_reasoning
            s1_streamed_reasoning = True
            if on_stage1_reasoning is not None:
                on_stage1_reasoning(chunk)

        def _on_s1_content(chunk: str) -> None:
            nonlocal s1_streamed_content
            s1_streamed_content = True
            if on_stage1_content is not None:
                on_stage1_content(chunk)

        try:
            reply_s1 = self._stream_chat_resilient(
                messages_s1,
                on_reasoning_token=_on_s1_reasoning,
                on_content_token=_on_s1_content,
                cancel_token=cancel_token,
                thinking=_thinking,
                reasoning_effort=_effort,
                stage_label="Stage 1",
            )
        except Exception as exc:
            if self._is_network_error(exc):
                logger.warning("Stage 1 network error: %s", exc)
                record = record.model_copy(
                    update={
                        "stage1_messages": messages_s1,
                        "exception": {
                            "type": "network_error",
                            "stage": "stage1",
                            "message": str(exc),
                        },
                    }
                )
                self._pending_writer.save_partial(record, "network_error")
                on_event(OrchestratorEvent.Stage1Failed)
                return record
            raise

        if not s1_streamed_reasoning and reply_s1.reasoning_content:
            _emit_buffered_stream(reply_s1.reasoning_content, on_stage1_reasoning)
        if not s1_streamed_content and reply_s1.content:
            _emit_buffered_stream(reply_s1.content, on_stage1_content)

        # ── Step 6: Post-Stage-1-call cancel check ────────────────────────────
        if cancel_token.is_set():
            record = record.model_copy(
                update={
                    "stage1_messages": messages_s1,
                    "stage1_response": reply_s1.raw,
                    "usage_total": _accumulate_usage(record.usage_total, reply_s1.usage),
                }
            )
            self._pending_writer.save_partial(record, "user_cancelled")
            on_event(OrchestratorEvent.Cancelled)
            return record

        # ── Step 7: Validate Stage 1 ──────────────────────────────────────────
        logger.debug("\n" + "="*80)
        logger.debug("【Stage 1 AI 完整响应】")
        logger.debug("="*80)
        logger.debug(reply_s1.content)
        if reply_s1.reasoning_content:
            logger.debug("\n--- [思考过程] ---\n%s", reply_s1.reasoning_content)
        logger.debug(
            "\n--- [Token 用量] prompt=%s completion=%s latency=%s ---",
            reply_s1.usage.prompt_tokens,
            reply_s1.usage.completion_tokens,
            _latency_ms_label(reply_s1.latency_ms),
        )
        logger.debug("="*80 + "\n")

        prev_s1: dict[str, Any] | None = None
        if previous_record is not None and int(incremental_new_bar_count or 0) > 0:
            prev_s1 = previous_record.stage1_diagnosis

        s1_usage_calls: list[Any] = [getattr(reply_s1, "usage", None)]

        def _call_s1_retry(msgs: list[dict]) -> Any:
            nonlocal s1_streamed_reasoning, s1_streamed_content
            on_event(OrchestratorEvent.Stage1Retry)
            s1_streamed_reasoning = False
            s1_streamed_content = False
            r = self._client.stream_chat(
                msgs,
                on_reasoning_token=_on_s1_reasoning,
                on_content_token=_on_s1_content,
                cancel_token=cancel_token,
                thinking=_thinking,
                reasoning_effort=_effort,
            )
            if not s1_streamed_reasoning and r.reasoning_content:
                _emit_buffered_stream(r.reasoning_content, on_stage1_reasoning)
            if not s1_streamed_content and r.content:
                _emit_buffered_stream(r.content, on_stage1_content)
            s1_usage_calls.append(getattr(r, "usage", None))
            return r

        s1_validate_kwargs = _filter_kwargs(
            self._validator.validate,
            {
                "kline_frame": frame,
                "incremental_new_bar_count": int(incremental_new_bar_count or 0),
                "incremental_previous_stage1": prev_s1,
                "active_position": active_position,
            },
        )
        vr_s1 = validate_with_retry(
            stage="stage1",
            messages=messages_s1,
            reply=reply_s1,
            validator=self._validator,
            validation_settings=self._validation_settings(),
            validate_kwargs=s1_validate_kwargs,
            call_api=_call_s1_retry,
            provider_settings=getattr(self._settings, "provider", None),
        )
        messages_s1 = vr_s1.messages
        reply_s1 = vr_s1.reply
        result_s1 = vr_s1.result
        if vr_s1.attempts > 1:
            logger.info("Stage 1 validation succeeded after %d attempt(s)", vr_s1.attempts)

        if isinstance(result_s1, ValidationError):
            err = result_s1
            err_message = _enrich_stage1_validation_message(err, reply_s1)
            logger.warning(
                "Stage 1 validation failed: category=%s message=%s",
                err.category,
                err_message,
            )
            record = record.model_copy(
                update={
                    "stage1_messages": messages_s1,
                    "stage1_response": reply_s1.raw,
                    "usage_total": _accumulate_usage_calls(record.usage_total, s1_usage_calls),
                    "exception": {
                        "type": "provider_error" if err.category == "e" else "validation_error",
                        "stage": "stage1",
                        "category": err.category,
                        "message": err_message,
                        "missing_fields": err.missing_fields,
                        "invalid_fields": err.invalid_fields,
                        "raw_text": err.raw_text,
                        "parse_position": err.parse_position,
                    },
                }
            )
            self._pending_writer.save_partial(record, f"stage1_{err.category}")
            on_event(OrchestratorEvent.Stage1Failed)
            return record

        # Validation passed — extract the parsed JSON
        assert isinstance(result_s1, Ok)
        stage1_json: dict = result_s1.obj

        # ── Step 9: Stage 1 done ──────────────────────────────────────────────
        on_event(OrchestratorEvent.Stage1Done)

        # ── Step 10: Route strategy files ─────────────────────────────────────
        if callable(self._router) and not hasattr(self._router, "route"):
            strategy_files: list[str] = self._router(stage1_json)
        else:
            strategy_files = self._router.route(stage1_json)

        # ── Step 11: Load experience entries ──────────────────────────────────
        cycle_position: str = stage1_json.get("cycle_position", "unknown")
        direction = str(stage1_json.get("direction", "") or "")
        patterns = stage1_json.get("detected_patterns") or []
        prompt_cfg = getattr(self._settings, "prompt", None) if self._settings else None
        max_exp = getattr(prompt_cfg, "experience_max_entries", 0) if prompt_cfg else 0
        max_chars = (
            getattr(prompt_cfg, "experience_max_chars_per_entry", 400) if prompt_cfg else 400
        )
        if max_exp <= 0:
            experience_entries = []
        elif hasattr(self._exp_reader, "read_for_stage2"):
            experience_entries = self._exp_reader.read_for_stage2(
                cycle_position,
                direction=direction,
                patterns=patterns,
                max_entries=max_exp,
                max_chars_per_entry=max_chars,
            )
        else:
            experience_entries = self._exp_reader.read_top5(cycle_position)[:max_exp]

        # ── Step 12: Pre-Stage-2 cancel check ────────────────────────────────
        if cancel_token.is_set():
            record = record.model_copy(
                update={
                    "stage1_messages": messages_s1,
                    "stage1_response": reply_s1.raw,
                    "stage1_diagnosis": stage1_json,
                    "strategy_files_used": strategy_files,
                    "experience_loaded": [
                        e.model_dump() if hasattr(e, "model_dump") else dict(e)
                        for e in experience_entries
                    ],
                    "usage_total": _accumulate_usage(record.usage_total, reply_s1.usage),
                }
            )
            self._pending_writer.save_partial(record, "user_cancelled")
            on_event(OrchestratorEvent.Cancelled)
            return record

        # ── Step 13: Stage 2 started ──────────────────────────────────────────
        on_event(OrchestratorEvent.Stage2Started)
        if on_stage2_files is not None:
            on_stage2_files(list(strategy_files))

        gate_result = str(stage1_json.get("gate_result", "proceed")).lower()
        if gate_result in ("wait", "unknown"):
            from pa_agent.ai.decision_tree import build_stage2_gate_wait_response

            if on_stage_prompt is not None:
                on_stage_prompt("stage2", "", "（阶段一闸门未通过，跳过阶段二模型调用）")
            short_msg = (
                f"阶段一 gate_result={gate_result}，程序已短路生成阶段二结果，"
                "未向模型发起请求。\n"
            )
            _emit_buffered_stream(short_msg, on_stage2_content)

            stage2_json = build_stage2_gate_wait_response(stage1_json)
            on_event(OrchestratorEvent.Stage2Done)
            logger.info("next_bar_prediction direction=null probs=null/null/null unpredictable=true (gate short-circuit)")
            usage_total = _accumulate_usage(record.usage_total, reply_s1.usage)
            record = record.model_copy(
                update={
                    "stage1_messages": messages_s1,
                    "stage1_response": reply_s1.raw,
                    "stage1_diagnosis": stage1_json,
                    "stage2_messages": [],
                    "stage2_response": None,
                    "stage2_decision": stage2_json,
                    "strategy_files_used": strategy_files,
                    "experience_loaded": [
                        e.model_dump() if hasattr(e, "model_dump") else dict(e)
                        for e in experience_entries
                    ],
                    "usage_total": usage_total,
                    "exception": None,
                }
            )
            self._pending_writer.save_full(record)
            on_event(OrchestratorEvent.RecordSaved)
            return record

        # ── Step 14: Build Stage 2 messages ───────────────────────────────────
        _enable_next_bar = bool(
            getattr(getattr(self._settings, "general", None), "enable_next_bar_prediction", False)
        )
        _flip_cooldown = int(
            getattr(
                getattr(self._settings, "general", None),
                "structure_flip_cooldown_bars",
                3,
            )
            or 3
        )
        _provider_settings = getattr(self._settings, "provider", None)
        # KV prefix-chain support check (informational; assembler may also consult it).
        _use_prefix_chain = _log_kv_prefix_chain_support(_provider_settings)

        stage2_build_kwargs = _filter_kwargs(
            self._assembler.build_stage2_continuation,
            {
                "frame": frame,
                "stage1_messages": messages_s1,
                "stage1_reply_content": reply_s1.content,
                "stage1_json": stage1_json,
                "strategy_files": strategy_files,
                "experience_entries": experience_entries,
                "decision_stance": record.meta.decision_stance,
                "previous_record": previous_record,
                "enable_next_bar_prediction": _enable_next_bar,
                "active_position": active_position,
                "provider_settings": _provider_settings,
                "use_prefix_chain": _use_prefix_chain,
                "structure_flip_cooldown_bars": _flip_cooldown,
            },
        )
        messages_s2 = self._assembler.build_stage2_continuation(**stage2_build_kwargs)

        # Ensure market-features block is present in the Stage 2 user prompt.
        messages_s2 = _inject_market_features_into_stage2_messages(messages_s2, frame)

        # ── Step 15: Call AI for Stage 2 ──────────────────────────────────────
        logger.debug("\n" + "="*80)
        logger.debug("【Stage 2 发送的完整 Prompt】")
        logger.debug("="*80)
        for msg in messages_s2:
            role = msg.get("role", "?").upper()
            content = msg.get("content", "")
            logger.debug("\n--- [%s] ---\n%s", role, content)
        logger.debug("="*80 + "\n")

        # Notify conversation tab of the prompt being sent
        if on_stage_prompt is not None:
            s2_system = next((m.get("content", "") for m in messages_s2 if m.get("role") == "system"), "")
            s2_user = next((m.get("content", "") for m in reversed(messages_s2) if m.get("role") == "user"), "")
            on_stage_prompt("stage2", s2_system, s2_user)

        s2_streamed_reasoning = False
        s2_streamed_content = False

        def _on_s2_reasoning(chunk: str) -> None:
            nonlocal s2_streamed_reasoning
            s2_streamed_reasoning = True
            if on_stage2_reasoning is not None:
                on_stage2_reasoning(chunk)

        def _on_s2_content(chunk: str) -> None:
            nonlocal s2_streamed_content
            s2_streamed_content = True
            if on_stage2_content is not None:
                on_stage2_content(chunk)

        try:
            reply_s2 = self._stream_chat_resilient(
                messages_s2,
                on_reasoning_token=_on_s2_reasoning,
                on_content_token=_on_s2_content,
                cancel_token=cancel_token,
                thinking=_thinking,
                reasoning_effort=_effort,
                stage_label="Stage 2",
            )
        except Exception as exc:
            if self._is_network_error(exc):
                logger.warning("Stage 2 network error: %s", exc)
                record = record.model_copy(
                    update={
                        "stage1_messages": messages_s1,
                        "stage1_response": reply_s1.raw,
                        "stage1_diagnosis": stage1_json,
                        "stage2_messages": messages_s2,
                        "strategy_files_used": strategy_files,
                        "experience_loaded": [
                            e.model_dump() if hasattr(e, "model_dump") else dict(e)
                            for e in experience_entries
                        ],
                        "usage_total": _accumulate_usage(record.usage_total, reply_s1.usage),
                        "exception": {
                            "type": "network_error",
                            "stage": "stage2",
                            "message": str(exc),
                        },
                    }
                )
                self._pending_writer.save_partial(record, "network_error")
                on_event(OrchestratorEvent.Stage2Failed)
                return record
            raise

        if not s2_streamed_reasoning and reply_s2.reasoning_content:
            _emit_buffered_stream(reply_s2.reasoning_content, on_stage2_reasoning)
        if not s2_streamed_content and reply_s2.content:
            _emit_buffered_stream(reply_s2.content, on_stage2_content)

        # ── Step 16: Post-Stage-2-call cancel check ───────────────────────────
        if cancel_token.is_set():
            record = record.model_copy(
                update={
                    "stage1_messages": messages_s1,
                    "stage1_response": reply_s1.raw,
                    "stage1_diagnosis": stage1_json,
                    "stage2_messages": messages_s2,
                    "stage2_response": reply_s2.raw,
                    "strategy_files_used": strategy_files,
                    "experience_loaded": [
                        e.model_dump() if hasattr(e, "model_dump") else dict(e)
                        for e in experience_entries
                    ],
                    "usage_total": _accumulate_usage(
                        _accumulate_usage(record.usage_total, reply_s1.usage),
                        reply_s2.usage,
                    ),
                }
            )
            self._pending_writer.save_partial(record, "user_cancelled")
            on_event(OrchestratorEvent.Cancelled)
            return record

        # ── Step 17: Validate Stage 2 ─────────────────────────────────────────
        logger.debug("\n" + "="*80)
        logger.debug("【Stage 2 AI 完整响应】")
        logger.debug("="*80)
        logger.debug(reply_s2.content)
        if reply_s2.reasoning_content:
            logger.debug("\n--- [思考过程] ---\n%s", reply_s2.reasoning_content)
        logger.debug(
            "\n--- [Token 用量] prompt=%s completion=%s latency=%s ---",
            reply_s2.usage.prompt_tokens,
            reply_s2.usage.completion_tokens,
            _latency_ms_label(reply_s2.latency_ms),
        )
        logger.debug("="*80 + "\n")

        s2_usage_calls: list[Any] = [getattr(reply_s2, "usage", None)]

        def _call_s2_retry(msgs: list[dict]) -> Any:
            nonlocal s2_streamed_reasoning, s2_streamed_content
            on_event(OrchestratorEvent.Stage2Retry)
            s2_streamed_reasoning = False
            s2_streamed_content = False
            r = self._client.stream_chat(
                msgs,
                on_reasoning_token=_on_s2_reasoning,
                on_content_token=_on_s2_content,
                cancel_token=cancel_token,
                thinking=_thinking,
                reasoning_effort=_effort,
            )
            if not s2_streamed_reasoning and r.reasoning_content:
                _emit_buffered_stream(r.reasoning_content, on_stage2_reasoning)
            if not s2_streamed_content and r.content:
                _emit_buffered_stream(r.content, on_stage2_content)
            s2_usage_calls.append(getattr(r, "usage", None))
            return r

        s2_validate_kwargs = _filter_kwargs(
            self._validator.validate,
            {
                "kline_frame": frame,
                "decision_stance": record.meta.decision_stance,
                "stage1_json": stage1_json,
                "skip_next_bar": not _enable_next_bar,
                "active_position": active_position,
                "previous_record": previous_record,
                "structure_flip_cooldown_bars": _flip_cooldown,
            },
        )
        vr_s2 = validate_with_retry(
            stage="stage2",
            messages=messages_s2,
            reply=reply_s2,
            validator=self._validator,
            validation_settings=self._validation_settings(),
            validate_kwargs=s2_validate_kwargs,
            call_api=_call_s2_retry,
            provider_settings=getattr(self._settings, "provider", None),
        )
        messages_s2 = vr_s2.messages
        reply_s2 = vr_s2.reply
        result_s2 = vr_s2.result
        if vr_s2.attempts > 1:
            logger.info("Stage 2 validation succeeded after %d attempt(s)", vr_s2.attempts)

        if isinstance(result_s2, ValidationError):
            err = result_s2
            err_message = _enrich_stage2_validation_message(err, reply_s2)
            preserved_s2 = _stage2_decision_from_validation_error(
                content=reply_s2.content or "",
                kline_frame=frame,
                decision_stance=record.meta.decision_stance,
                stage1_json=stage1_json,
                skip_next_bar=not _enable_next_bar,
            )
            exc_payload: dict[str, Any] = {
                "type": "provider_error" if err.category == "e" else "validation_error",
                "stage": "stage2",
                "category": err.category,
                "message": err_message,
                "missing_fields": err.missing_fields,
                "invalid_fields": err.invalid_fields,
                "raw_text": err.raw_text,
                "parse_position": err.parse_position,
                "decision_preserved": preserved_s2 is not None,
            }
            from pa_agent.positions.decision_fields import (
                should_apply_position_despite_validation,
            )

            exc_payload["position_apply_allowed"] = (
                should_apply_position_despite_validation(
                    exc_payload,
                    stage2_decision=preserved_s2,
                )
            )
            logger.warning(
                "Stage 2 validation failed: category=%s preserved=%s apply=%s",
                err.category,
                preserved_s2 is not None,
                exc_payload["position_apply_allowed"],
            )
            record = record.model_copy(
                update={
                    "stage1_messages": messages_s1,
                    "stage1_response": reply_s1.raw,
                    "stage1_diagnosis": stage1_json,
                    "stage2_messages": messages_s2,
                    "stage2_response": reply_s2.raw,
                    "stage2_decision": preserved_s2,
                    "strategy_files_used": strategy_files,
                    "experience_loaded": [
                        e.model_dump() if hasattr(e, "model_dump") else dict(e)
                        for e in experience_entries
                    ],
                    "usage_total": _accumulate_usage_calls(
                        _accumulate_usage_calls(record.usage_total, s1_usage_calls),
                        s2_usage_calls,
                    ),
                    "exception": exc_payload,
                }
            )
            self._pending_writer.save_partial(record, f"stage2_{err.category}")
            on_event(OrchestratorEvent.Stage2Failed)
            return record

        # Validation passed
        assert isinstance(result_s2, Ok)
        stage2_json: dict = result_s2.obj
        if not _enable_next_bar and isinstance(stage2_json, dict):
            stage2_json = copy.deepcopy(stage2_json)
            stage2_json.pop("next_bar_prediction", None)

        # Apply program decision-continuity guard (mirrors upstream normalizer).
        if isinstance(stage2_json, dict):
            stage2_json = _apply_continuity_guard_to_stage2(
                stage2_json,
                frame=frame,
                stage1_json=stage1_json,
                previous_record=previous_record,
                cooldown_bars=_flip_cooldown,
            )

        # ── Step 19: Stage 2 done ─────────────────────────────────────────────
        on_event(OrchestratorEvent.Stage2Done)

        # ── Step 19.5: Log next_bar_prediction (R9.3, NFR2.1) ───────────────────
        _pred = stage2_json if isinstance(stage2_json, dict) else {}
        _nb_pred = _pred.get("next_bar_prediction")
        if not _enable_next_bar:
            logger.info("next_bar_prediction omitted (feature disabled)")
        elif isinstance(_nb_pred, dict):
            if _nb_pred.get("unpredictable"):
                logger.info("next_bar_prediction direction=null probs=null/null/null unpredictable=true")
            else:
                _probs = _nb_pred.get("probabilities") or {}
                logger.info(
                    "next_bar_prediction direction=%s probs=%s/%s/%s unpredictable=false",
                    _nb_pred.get("direction"),
                    _probs.get("bullish"),
                    _probs.get("bearish"),
                    _probs.get("neutral"),
                )
        elif _enable_next_bar:
            logger.info("next_bar_prediction absent from stage2 response")

        _nc_pred = _pred.get("next_cycle_prediction")
        if isinstance(_nc_pred, dict):
            if _nc_pred.get("unpredictable"):
                logger.info("next_cycle_prediction cycle=null unpredictable=true")
            else:
                logger.info(
                    "next_cycle_prediction cycle=%s direction=%s unpredictable=false",
                    _nc_pred.get("cycle"),
                    _nc_pred.get("direction"),
                )
        else:
            logger.info("next_cycle_prediction absent from stage2 response")

        # ── Step 20: Build final record ───────────────────────────────────────
        usage_total = _accumulate_usage_calls(
            _accumulate_usage_calls(record.usage_total, s1_usage_calls),
            s2_usage_calls,
        )
        record = record.model_copy(
            update={
                "stage1_messages": messages_s1,
                "stage1_response": reply_s1.raw,
                "stage1_diagnosis": stage1_json,
                "stage2_messages": messages_s2,
                "stage2_response": reply_s2.raw,
                "stage2_decision": stage2_json,
                "strategy_files_used": strategy_files,
                "experience_loaded": [
                    e.model_dump() if hasattr(e, "model_dump") else dict(e)
                    for e in experience_entries
                ],
                "usage_total": usage_total,
                "exception": None,
            }
        )

        # ── Step 22: Persist full record ──────────────────────────────────────
        self._pending_writer.save_full(record)

        # ── Step 23: Record saved event ───────────────────────────────────────
        on_event(OrchestratorEvent.RecordSaved)

        # ── Step 24: Return ───────────────────────────────────────────────────
        return record

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _thinking_params(self) -> tuple[bool, str]:
        """Return (thinking, reasoning_effort) from settings defaults."""
        if self._settings is None:
            return True, "high"
        p = self._settings.provider
        return p.thinking, p.reasoning_effort

    def _stream_chat_resilient(
        self,
        messages: list[dict[str, Any]],
        *,
        on_reasoning_token: Callable[[str], None] | None,
        on_content_token: Callable[[str], None] | None,
        cancel_token: CancelToken,
        thinking: bool,
        reasoning_effort: str,
        stage_label: str,
        stage_id: str = "",
    ) -> Any:
        """Call stream_chat with empty-content fallback and provider failover."""
        stage_key = stage_id or ("stage1" if "1" in stage_label else "stage2")
        original_model = (
            self._settings.provider.model if self._settings is not None else ""
        )
        tried_qclaw = False
        tried_cursor = False
        tried_workbuddy = False
        while True:
            try:
                return _stream_stage_with_empty_content_fallback(
                    self._client,
                    messages,
                    stage=stage_key,
                    thinking=thinking,
                    reasoning_effort=reasoning_effort,
                    cancel_token=cancel_token,
                    on_reasoning_token=on_reasoning_token,
                    on_content_token=on_content_token,
                )
            except Exception as exc:
                if not self._is_network_error(exc):
                    raise
                # Try WorkBuddy fallback first (if model is openclaw_wb),
                # then Cursor (if model is openclaw_cs),
                # then QClaw fallback (if model is openclaw)
                if not tried_workbuddy and self._try_workbuddy_fallback(
                    original_model=original_model
                ):
                    tried_workbuddy = True
                    logger.info(
                        "%s network error (%s); applied WorkBuddy provider — retrying",
                        stage_label,
                        exc,
                    )
                elif not tried_cursor and self._try_cursor_fallback(
                    original_model=original_model
                ):
                    tried_cursor = True
                    logger.info(
                        "%s network error (%s); applied Cursor provider — retrying",
                        stage_label,
                        exc,
                    )
                elif not tried_qclaw and self._try_qclaw_fallback(
                    original_model=original_model
                ):
                    tried_qclaw = True
                    logger.info(
                        "%s network error (%s); applied QClaw provider — retrying",
                        stage_label,
                        exc,
                    )
                else:
                    raise

    def _try_qclaw_fallback(self, *, original_model: str = "") -> bool:
        """Apply local QClaw provider (like settings Save with model=openclaw)."""
        from pa_agent.ai.qclaw_connector import (
            apply_qclaw_provider_to_settings,
            is_openclaw_model,
        )
        from pa_agent.config.paths import SETTINGS_JSON_PATH

        if not is_openclaw_model(original_model):
            return False
        if self._settings is None:
            return False

        from pa_agent.config.settings import save_settings
        from pa_agent.util.logging import update_api_key

        err = apply_qclaw_provider_to_settings(self._settings)
        if err:
            logger.warning("QClaw auto-fallback unavailable: %s", err)
            return False

        self._client.update_provider(self._settings.provider)
        try:
            save_settings(self._settings, SETTINGS_JSON_PATH)
            update_api_key(self._settings.provider.api_key)
        except Exception as save_exc:  # noqa: BLE001
            logger.warning("QClaw fallback applied but settings save failed: %s", save_exc)

        logger.info(
            "QClaw auto-fallback: model=%s base_url=%s",
            self._settings.provider.model,
            self._settings.provider.base_url,
        )
        return True

    def _try_cursor_fallback(self, *, original_model: str = "") -> bool:
        """Apply Cursor route via QClaw (like settings Save with model=openclaw_cs)."""
        from pa_agent.ai.cursor_connector import (
            apply_cursor_provider_to_settings,
            is_openclaw_cs_model,
        )
        from pa_agent.config.paths import SETTINGS_JSON_PATH

        if not is_openclaw_cs_model(original_model):
            return False
        if self._settings is None:
            return False

        from pa_agent.config.settings import save_settings
        from pa_agent.util.logging import update_api_key

        err = apply_cursor_provider_to_settings(
            self._settings,
            preferred_model=original_model,
        )
        if err:
            logger.warning("Cursor auto-fallback unavailable: %s", err)
            return False

        self._client.update_provider(self._settings.provider)
        try:
            save_settings(self._settings, SETTINGS_JSON_PATH)
            update_api_key(self._settings.provider.api_key)
        except Exception as save_exc:  # noqa: BLE001
            logger.warning("Cursor fallback applied but settings save failed: %s", save_exc)

        logger.info(
            "Cursor auto-fallback: model=%s base_url=%s",
            self._settings.provider.model,
            self._settings.provider.base_url,
        )
        return True

    def _try_workbuddy_fallback(self, *, original_model: str = "") -> bool:
        """Apply WorkBuddy provider (like settings Save with model=openclaw_wb)."""
        from pa_agent.ai.workbuddy_connector import (
            apply_workbuddy_provider_to_settings,
            is_openclaw_wb_model,
        )
        from pa_agent.config.paths import SETTINGS_JSON_PATH

        if not is_openclaw_wb_model(original_model):
            return False
        if self._settings is None:
            return False

        from pa_agent.config.settings import save_settings
        from pa_agent.util.logging import update_api_key

        err = apply_workbuddy_provider_to_settings(self._settings)
        if err:
            logger.warning("WorkBuddy auto-fallback unavailable: %s", err)
            return False

        self._client.update_provider(self._settings.provider)
        try:
            save_settings(self._settings, SETTINGS_JSON_PATH)
            update_api_key(self._settings.provider.api_key)
        except Exception as save_exc:  # noqa: BLE001
            logger.warning("WorkBuddy fallback applied but settings save failed: %s", save_exc)

        logger.info(
            "WorkBuddy auto-fallback: model=%s base_url=%s",
            self._settings.provider.model,
            self._settings.provider.base_url,
        )
        return True

    @staticmethod
    def _is_network_error(exc: Exception) -> bool:
        """Return True if *exc* is a network/timeout error (SDK, httpx, or OS reset)."""
        from pa_agent.ai.deepseek_client import CancelledError

        if isinstance(exc, CancelledError):
            return False

        try:
            import openai  # type: ignore[import]

            if isinstance(
                exc,
                (
                    openai.APITimeoutError,
                    openai.APIConnectionError,
                    openai.APIStatusError,
                ),
            ):
                return True
        except ImportError:
            pass

        try:
            import httpx  # type: ignore[import]

            if isinstance(
                exc,
                (
                    httpx.ReadError,
                    httpx.ConnectError,
                    httpx.TimeoutException,
                    httpx.RemoteProtocolError,
                ),
            ):
                return True
        except ImportError:
            pass

        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, TimeoutError)):
            return True
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (
            10054,  # WSAECONNRESET — remote host closed connection
            10053,  # WSAECONNABORTED
            10060,  # WSAETIMEDOUT
        ):
            return True

        cause = exc.__cause__
        if cause is not None and cause is not exc:
            return TwoStageOrchestrator._is_network_error(cause)
        return False
