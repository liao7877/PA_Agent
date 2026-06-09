"""Application entry point for PA Agent."""
from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    # Logging is configured inside AppContext.bootstrap() with the real API key
    # for masking. No need to call configure_logging() here separately.

    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("PA Agent")

    from pa_agent.gui.theme import apply_theme
    apply_theme(app)

    logger.info("PA Agent starting up")

    from pa_agent.licensing.activation_dialog import ensure_license_or_exit
    from pa_agent.licensing.validator import LicenseValidator

    license_validator = LicenseValidator()
    license_info = ensure_license_or_exit(app, license_validator)
    logger.info(
        "License ok: expires=%s days_remaining=%s",
        LicenseValidator.format_expiry(license_info.expires_at),
        license_info.days_remaining,
    )

    # Bootstrap all components (settings, data source, AI client, etc.)
    from pa_agent.app_context import AppContext
    ctx = AppContext.bootstrap()

    # Update logging with the real API key now that settings are loaded
    if ctx.settings is not None:
        from pa_agent.util.logging import update_api_key
        update_api_key(ctx.settings.provider.api_key)

    # Build and show the main window
    from pa_agent.gui.main_window import MainWindow
    window = MainWindow(ctx, license_validator=license_validator)
    window.show()

    logger.info("Main window shown")
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
