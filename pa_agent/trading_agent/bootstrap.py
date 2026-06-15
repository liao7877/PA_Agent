"""Post-bootstrap enrichment for Trading Agent services."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pa_agent.app_context import AppContext


def enrich_app_context(ctx: AppContext) -> AppContext:
    """Attach notification and position tracking without touching upstream bootstrap body."""
    from pa_agent.notification.service import NotificationService
    from pa_agent.positions.store import PositionStore
    from pa_agent.positions.tracker import PositionTracker

    logger = ctx.logger
    settings = ctx.settings
    ctx.notifier = NotificationService(settings=settings, logger=logger)
    ctx.position_tracker = PositionTracker(
        store=PositionStore(),
        notifier=ctx.notifier,
    )
    return ctx
