"""Trading Agent application entry (licensing + window title)."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

from pa_agent.trading_agent import PRODUCT_NAME

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    # Early diagnostics before Qt / heavy imports: crash dumps + file logging.
    from pa_agent.util.crash_diagnostics import enable_crash_diagnostics, log_startup_diagnostics
    from pa_agent.util.logging import configure_logging

    enable_crash_diagnostics()
    configure_logging()
    log_startup_diagnostics()

    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName(PRODUCT_NAME)

    from pa_agent.gui.theme import apply_theme

    apply_theme(app)

    logger.info("%s starting up", PRODUCT_NAME)

    from pa_agent.licensing.activation_dialog import ensure_license_or_exit
    from pa_agent.licensing.validator import LicenseValidator

    license_validator = LicenseValidator()
    license_info = ensure_license_or_exit(app, license_validator)
    logger.info(
        "License ok: expires=%s days_remaining=%s",
        LicenseValidator.format_expiry(license_info.expires_at),
        license_info.days_remaining,
    )

    from pa_agent.app_context import AppContext

    ctx = AppContext.bootstrap()

    if ctx.settings is not None:
        from pa_agent.util.logging import update_api_key

        update_api_key(ctx.settings.provider.api_key)

    from pa_agent.gui.main_window import MainWindow

    window = MainWindow(ctx, license_validator=license_validator)
    window.show()

    logger.info("Main window shown")
    return app.exec()
