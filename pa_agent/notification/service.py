"""NotificationService — central dispatcher for outbound notifications.

Reads the live ``NotificationSettings`` on every call (so settings changes take
effect without re-instantiation), filters by master switch + per-scene toggle,
fans the message out to all configured channels, and runs the HTTP work on a
background daemon thread so the GUI never blocks.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from pa_agent.notification.channels import DingTalkChannel, WeChatChannel
from pa_agent.notification.events import NotificationEvent, NotificationMessage
from pa_agent.notification import formatter


class NotificationService:
    """Dispatch :class:`NotificationMessage` to configured channels.

    Parameters
    ----------
    settings:
        The root ``Settings`` object. The service reads ``settings.notification``
        lazily on each dispatch, so external mutation is picked up immediately.
    logger:
        Optional logger; defaults to the ``pa_agent`` logger.
    """

    def __init__(
        self,
        *,
        settings: Any,
        logger: logging.Logger | None = None,
        instrument_manager: Any = None,
    ) -> None:
        self._settings = settings
        self._logger = logger or logging.getLogger("pa_agent")
        self._instrument_manager = instrument_manager

    # ── Public API ────────────────────────────────────────────────────────
    def notify(self, message: NotificationMessage, *, instrument: Any = None) -> None:
        """Dispatch *message* if enabled. Non-blocking (runs in background)."""
        cfg = self._notification_cfg(instrument, message)
        if cfg is None or not getattr(cfg, "enabled", False):
            return
        if not self._scene_enabled(cfg, message.event):
            return
        channels = self._build_channels(cfg)
        if not channels:
            self._logger.info(
                "Notification skipped (%s): no channel configured", message.event.value
            )
            return
        thread = threading.Thread(
            target=self._dispatch_sync,
            args=(channels, message),
            name="notify-dispatch",
            daemon=True,
        )
        thread.start()

    def notify_api_failure(
        self,
        *,
        message: str,
        symbol: str = "",
        timeframe: str = "",
        stage: str = "",
        source: str = "analysis",
        exception: dict | None = None,
        instrument: Any = None,
    ) -> None:
        """Dispatch an API connectivity/upstream failure notification."""
        self.notify(
            formatter.format_api_error(
                message=message,
                symbol=symbol,
                timeframe=timeframe,
                stage=stage,
                source=source,
                exception=exception,
            ),
            instrument=instrument,
        )

    def notify_record(self, record: Any, *, active_position: Any = None, instrument: Any = None) -> None:
        """Convenience: classify an ``AnalysisRecord`` and dispatch.

        Handles the NEW_ORDER / NO_TRADE / ERROR scenes derived from a single
        analysis run. ENTRY_FILLED / EXIT / MANAGE come from the position
        tracker via :meth:`notify`.
        """
        del active_position
        cfg = self._notification_cfg(instrument)
        if cfg is None or not getattr(cfg, "enabled", False):
            return
        try:
            meta = getattr(record, "meta", None)
            symbol = getattr(meta, "symbol", "") if meta else ""
            timeframe = getattr(meta, "timeframe", "") if meta else ""
            exception = getattr(record, "exception", None)
            decision = getattr(record, "stage2_decision", None)
            from pa_agent.positions.decision_fields import (
                is_actionable_trade_decision,
                should_apply_position_despite_validation,
            )

            exc = exception if isinstance(exception, dict) else None
            if exc and formatter.is_api_exception(exc):
                self.notify_api_failure(
                    message=str(exc.get("message") or ""),
                    symbol=symbol,
                    timeframe=timeframe,
                    stage=str(exc.get("stage") or ""),
                    source=str(exc.get("source") or "analysis"),
                    exception=exc,
                    instrument=instrument,
                )
                return
            actionable = is_actionable_trade_decision(decision)
            trade_ok = should_apply_position_despite_validation(
                exc, stage2_decision=decision
            )
            if exc:
                if actionable and not trade_ok:
                    self.notify(
                        formatter.format_error(
                            symbol=symbol, timeframe=timeframe, exception=exc
                        ),
                        instrument=instrument,
                    )
                    return
                if not decision and not exc.get("decision_preserved"):
                    self.notify(
                        formatter.format_error(
                            symbol=symbol, timeframe=timeframe, exception=exc
                        ),
                        instrument=instrument,
                    )
                    return
            if not decision:
                return
            stage1 = getattr(record, "stage1_diagnosis", None)
            self.notify(
                formatter.format_decision(
                    symbol=symbol,
                    timeframe=timeframe,
                    decision=decision,
                    stage1_diagnosis=stage1,
                ),
                instrument=instrument,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("notify_record failed: %s", exc)

    # ── Internals ─────────────────────────────────────────────────────────
    def _notification_cfg(self, instrument: Any = None, message: NotificationMessage | None = None) -> Any:
        if instrument is None and message is not None and self._instrument_manager is not None:
            fields = getattr(message, "fields", {}) or {}
            symbol = str(fields.get("symbol") or "")
            timeframe = str(fields.get("timeframe") or "")
            for runtime in self._instrument_manager.runtimes():
                cfg = runtime.config
                if cfg.symbol == symbol and cfg.timeframe == timeframe:
                    instrument = cfg
                    break
        if instrument is not None:
            manager = self._instrument_manager
            if manager is not None:
                try:
                    return manager.effective_settings(instrument).notification
                except Exception:  # noqa: BLE001
                    pass
            if getattr(instrument, "notification_override_enabled", False):
                return getattr(instrument, "notification", None)
        if self._settings is None:
            return None
        return getattr(self._settings, "notification", None)

    @staticmethod
    def _scene_enabled(cfg: Any, event: NotificationEvent) -> bool:
        return bool(getattr(cfg, event.setting_attr, False))

    def _build_channels(self, cfg: Any) -> list:
        timeout = int(getattr(cfg, "request_timeout_s", 10) or 10)
        channels: list = []
        ding = (getattr(cfg, "dingtalk_webhook", "") or "").strip()
        if ding:
            channels.append(
                DingTalkChannel(
                    webhook=ding,
                    secret=(getattr(cfg, "dingtalk_secret", "") or "").strip(),
                    timeout_s=timeout,
                )
            )
        wechat = (getattr(cfg, "wechat_webhook", "") or "").strip()
        if wechat:
            channels.append(WeChatChannel(webhook=wechat, timeout_s=timeout))
        return channels

    def _dispatch_sync(self, channels: list, message: NotificationMessage) -> None:
        for channel in channels:
            try:
                result = channel.send(message)
                if result.ok:
                    self._logger.info(
                        "Notification sent via %s (%s)", channel.name, message.event.value
                    )
                else:
                    self._logger.warning(
                        "Notification via %s failed: %s",
                        channel.name,
                        result.error or result.status,
                    )
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "Notification via %s raised: %s", channel.name, exc
                )
