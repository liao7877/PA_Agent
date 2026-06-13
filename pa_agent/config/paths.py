"""Centralised path constants for Trading Agent.

All runtime directories are rooted at PROJECT_ROOT.
Import this module everywhere instead of hard-coding paths.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pa_agent.licensing.packaged import is_packaged_build


def _bundle_root() -> Path:
    if is_packaged_build():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent.parent


def _runtime_root() -> Path:
    if is_packaged_build() and sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        root = base / "Trading_Agent"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(__file__).resolve().parent.parent.parent


# ── Root ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT: Path = _runtime_root()
BUNDLE_ROOT: Path = _bundle_root()

# ── Prompt engineering assets (read-only at runtime) ─────────────────────────
PROMPT_DIR: Path = (BUNDLE_ROOT if is_packaged_build() else PROJECT_ROOT) / "prompt_engineering"

# Alias kept for backward compat with design doc
PA_AGENT_DIR: Path = PROJECT_ROOT

# ── Runtime write directories ─────────────────────────────────────────────────
RECORDS_DIR: Path = PROJECT_ROOT / "records"
RECORDS_PENDING_DIR: Path = RECORDS_DIR / "pending"
EXPERIENCE_DIR: Path = PROJECT_ROOT / "experience"
CONFIG_DIR: Path = PROJECT_ROOT / "config"
LOGS_DIR: Path = PROJECT_ROOT / "logs"

# ── Individual file paths ─────────────────────────────────────────────────────
SETTINGS_JSON_PATH: Path = CONFIG_DIR / "settings.json"
LOG_FILE_PATH: Path = LOGS_DIR / "pa_agent.log"
POSITIONS_JSON_PATH: Path = RECORDS_DIR / "positions.json"
