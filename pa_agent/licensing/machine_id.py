"""Stable machine fingerprint for license binding (Windows-first)."""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys


def _wmic_value(alias: str, field: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        completed = subprocess.run(
            ["wmic", alias, "get", field],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return ""
    return lines[1].strip()


def _collect_parts() -> list[str]:
    parts: list[str] = []
    if sys.platform == "win32":
        parts.extend(
            [
                _wmic_value("csproduct", "UUID"),
                _wmic_value("baseboard", "SerialNumber"),
                _wmic_value("diskdrive", "SerialNumber"),
            ]
        )
    parts.append(platform.node())
    parts.append(platform.machine())
    return [p for p in parts if p and p not in {"None", "To be filled by O.E.M.", "Default string"}]


def get_machine_fingerprint() -> str:
    """Return a short, stable fingerprint for display and license binding."""
    raw = "|".join(_collect_parts()) or platform.node() or "unknown-host"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest[:16].upper()


def format_machine_code(fingerprint: str) -> str:
    fp = fingerprint.replace("-", "").upper()
    return "-".join(fp[i : i + 4] for i in range(0, len(fp), 4))
