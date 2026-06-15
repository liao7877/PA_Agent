"""Position lifecycle tracking package.

Turns one-shot analysis decisions into tracked positions so subsequent
analyses manage an open trade instead of re-deciding from scratch.

Public API:
- :class:`PositionState` / :class:`PositionStatus` (model)
- :class:`PositionStore` (persistence)
- :class:`PositionTracker` (lifecycle + fill/exit detection)
"""

from pa_agent.positions.model import PositionState, PositionStatus
from pa_agent.positions.store import PositionStore
from pa_agent.positions.tracker import PositionTracker

__all__ = [
    "PositionState",
    "PositionStatus",
    "PositionStore",
    "PositionTracker",
]
