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

    def __init__(self, *, settings: Any, logger: logging.Logger | None = None) -> None:
        self._settings = settings
        self._logger = logger or logging.getLogger("pa_agent")

    # ── Public API ────────────────────────────────────────────────────────
    def notify(self, message: NotificationMessage) -> None:
        """Dispatch *message* if enabled. Non-blocking (runs in background)."""
        cfg = self._notification_cfg()
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

    def notify_record(self, record: Any) -> None:
        """Convenience: classify an ``AnalysisRecord`` and dispatch.

        Handles the NEW_ORDER / NO_TRADE / ERROR scenes derived from a single
        analysis run. ENTRY_FILLED / EXIT / MANAGE come from the position
        tracker via :meth:`notify`.
        """
        cfg = self._notification_cfg()
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
            actionable = is_actionable_trade_decision(decision)
            trade_ok = should_apply_position_despite_validation(
                exc, stage2_decision=decision
            )
            if exc:
                if actionable and not trade_ok:
                    self.notify(
                        formatter.format_error(
                            symbol=symbol, timeframe=timeframe, exception=exc
                        )
                    )
                    return
                if not decision and not exc.get("decision_preserved"):
                    self.notify(
                        formatter.format_error(
                            symbol=symbol, timeframe=timeframe, exception=exc
                        )
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
                )
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("notify_record failed: %s", exc)

    # ── Internals ─────────────────────────────────────────────────────────
    def _notification_cfg(self) -> Any:
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
