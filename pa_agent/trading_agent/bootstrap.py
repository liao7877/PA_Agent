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
    from pa_agent.instruments import InstrumentRuntimeManager

    logger = ctx.logger
    settings = ctx.settings
    if getattr(ctx, "instrument_manager", None) is None:
        ctx.instrument_manager = InstrumentRuntimeManager(settings=settings, logger_=logger)
    ctx.notifier = NotificationService(
        settings=settings,
        logger=logger,
        instrument_manager=ctx.instrument_manager,
    )
    ctx.position_tracker = PositionTracker(
        store=PositionStore(),
        notifier=ctx.notifier,
    )
    return ctx
