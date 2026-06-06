"""Outbound notification package.

Dispatches decision / position messages to configured channels
(DingTalk group robot, WeChat via Bark/Server酱/企业微信 webhook).

Public entry point: :class:`NotificationService`.
"""

from pa_agent.notification.events import NotificationEvent, NotificationMessage
from pa_agent.notification.service import NotificationService

__all__ = [
    "NotificationEvent",
    "NotificationMessage",
    "NotificationService",
]
