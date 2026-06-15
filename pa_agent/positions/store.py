"""Persistence for tracked positions.

Stores the *active* position per ``symbol|timeframe`` in a single JSON file
(``records/positions.json``). Closed positions are appended to an in-file
history list so they survive restarts for audit, but only one active position
per key is kept.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from pa_agent.positions.model import PositionState, PositionStatus

logger = logging.getLogger("pa_agent")


class PositionStore:
    """Load/save active positions keyed by ``symbol|timeframe``."""

    def __init__(self, *, path: Path | None = None) -> None:
        if path is None:
            from pa_agent.config.paths import POSITIONS_JSON_PATH

            path = POSITIONS_JSON_PATH
        self._path = path
        self._active: dict[str, PositionState] = {}
        self._history: list[dict] = []
        self._load()

    # ── Public API ────────────────────────────────────────────────────────
    def get_active(self, symbol: str, timeframe: str) -> Optional[PositionState]:
        pos = self._active.get(self._key(symbol, timeframe))
        if pos is not None and pos.is_active:
            return pos
        return None

    def upsert_active(self, position: PositionState) -> None:
        """Set the active position for its key (replaces any existing one)."""
        self._active[position.key()] = position
        self._save()

    def close_active(self, position: PositionState) -> None:
        """Move *position* to history and clear it from active set."""
        position.status = PositionStatus.CLOSED
        key = position.key()
        self._history.append(position.model_dump(mode="json"))
        self._active.pop(key, None)
        self._save()

    def clear_active(self, symbol: str, timeframe: str) -> None:
        """Remove the active position for a key without recording history."""
        if self._active.pop(self._key(symbol, timeframe), None) is not None:
            self._save()

    def all_active(self) -> list[PositionState]:
        return [p for p in self._active.values() if p.is_active]

    # ── Internals ─────────────────────────────────────────────────────────
    @staticmethod
    def _key(symbol: str, timeframe: str) -> str:
        return f"{symbol}|{timeframe}"

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("positions.json unreadable (%s); starting empty", exc)
            return
        active = raw.get("active", {}) or {}
        for key, data in active.items():
            try:
                self._active[key] = PositionState.model_validate(data)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping invalid position %s: %s", key, exc)
        self._history = list(raw.get("history", []) or [])

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "active": {k: v.model_dump(mode="json") for k, v in self._active.items()},
            "history": self._history[-200:],  # cap history growth
        }
        try:
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Failed to write positions.json: %s", exc)
