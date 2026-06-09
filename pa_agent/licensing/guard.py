"""Periodic license re-validation while the app is running."""
from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from pa_agent.licensing.validator import LicenseInfo, LicenseValidator


class LicenseGuard(QObject):
    expired = pyqtSignal(LicenseInfo)

    def __init__(
        self,
        validator: LicenseValidator | None = None,
        interval_ms: int = 5 * 60 * 1000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._validator = validator or LicenseValidator()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _on_tick(self) -> None:
        info = self._validator.check()
        if not info.ok:
            self.expired.emit(info)
