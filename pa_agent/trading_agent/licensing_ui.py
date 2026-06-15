"""License guard and About-menu wiring for the main window."""

from __future__ import annotations

from typing import Any

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QMenuBar


def wire_licensing(window: QMainWindow, license_validator: Any = None) -> None:
    """Install license guard and About-menu actions on *window*."""
    window._license_validator = license_validator  # noqa: SLF001

    menu_bar: QMenuBar | None = window.menuBar()
    if menu_bar is not None:
        about_menu = None
        for action in menu_bar.actions():
            if action.text() == "关于":
                about_menu = action.menu()
                break
        if about_menu is None:
            about_menu = menu_bar.addMenu("关于")
        license_info_action = QAction("授权信息 / 续期", window)
        license_info_action.triggered.connect(
            lambda: open_license_info_dialog(window)
        )
        about_menu.addAction(license_info_action)

    start_license_guard(window, license_validator)


def open_license_info_dialog(window: QMainWindow) -> None:
    from pa_agent.licensing.license_info_dialog import LicenseInfoDialog
    from pa_agent.licensing.validator import LicenseValidator

    validator = getattr(window, "_license_validator", None) or LicenseValidator()
    LicenseInfoDialog(validator, parent=window).exec()


def start_license_guard(window: QMainWindow, license_validator: Any = None) -> None:
    from pa_agent.licensing.guard import LicenseGuard

    guard = LicenseGuard(validator=license_validator, parent=window)
    guard.expired.connect(lambda info: on_license_expired(window, info))
    guard.start()
    window._license_guard = guard  # noqa: SLF001


def on_license_expired(window: QMainWindow, info: Any) -> None:
    guard = getattr(window, "_license_guard", None)
    if guard is not None:
        guard.stop()
    QMessageBox.critical(
        window,
        "授权失效",
        f"{info.message}\n\n程序将退出，请联系供应商续期。",
    )
    window.close()


def require_license_for_submit(window: QMainWindow) -> None:
    from pa_agent.licensing.enforce import require_active_license

    require_active_license(
        getattr(window, "_license_validator", None),
        context="submit_analysis",
        parent=window,
    )
