"""Central license enforcement helpers for scattered runtime checks."""
from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from pa_agent.licensing.packaged import is_packaged_build

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

    from pa_agent.licensing.validator import LicenseInfo, LicenseValidator

logger = logging.getLogger(__name__)

GUARD_INTERVAL_MS = 90_000


class LicenseEnforcementError(RuntimeError):
    def __init__(self, info: LicenseInfo) -> None:
        super().__init__(info.message)
        self.info = info


def require_active_license(
    validator: LicenseValidator | None = None,
    *,
    context: str = "",
    parent: QWidget | None = None,
) -> None:
    """Re-validate license in packaged builds; terminate the app on failure."""
    if not is_packaged_build():
        return

    from pa_agent.licensing.validator import LicenseValidator

    v = validator or LicenseValidator()
    info = v.check()
    if info.ok:
        return

    label = f"[{context}] " if context else ""
    logger.warning("%slicense enforcement failed: %s", label, info.message)
    _exit_due_to_license(info, parent=parent)


def _exit_due_to_license(info: LicenseInfo, *, parent: QWidget | None = None) -> None:
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance()
    if app is not None:
        QMessageBox.critical(
            parent,
            "授权失效",
            f"{info.message}\n\n程序将退出，请联系供应商续期。",
        )
    raise SystemExit(1)
