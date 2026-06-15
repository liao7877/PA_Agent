"""Bundled vendor license-server client configuration."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pa_agent.licensing.packaged import is_packaged_build

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LicenseClientConfig:
    online_enabled: bool = False
    server_url: str = ""
    client_api_key: str = ""

    @property
    def active(self) -> bool:
        return self.online_enabled and bool(self.server_url.strip())


def _config_candidates() -> list[Path]:
    from pa_agent.config.paths import BUNDLE_ROOT, CONFIG_DIR

    names = ("license_client.json", "license_client.example.json")
    paths: list[Path] = []
    if is_packaged_build():
        for name in names:
            paths.append(BUNDLE_ROOT / "config" / name)
    for name in names:
        paths.append(CONFIG_DIR / name)
    # De-duplicate while preserving order
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def load_license_client_config() -> LicenseClientConfig:
    for path in _config_candidates():
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return LicenseClientConfig(
                online_enabled=bool(raw.get("online_enabled", False)),
                server_url=str(raw.get("server_url", "") or "").strip().rstrip("/"),
                client_api_key=str(raw.get("client_api_key", "") or "").strip(),
            )
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("license client config unreadable (%s): %s", path, exc)
    return LicenseClientConfig()
