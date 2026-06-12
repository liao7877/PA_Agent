"""Detect whether PA Agent is running from a packaged release build."""
from __future__ import annotations

import sys


def is_packaged_build() -> bool:
    """True for PyInstaller/Nuitka builds; False when running from source."""
    if getattr(sys, "frozen", False):
        return True
    try:
        import __main__

        if getattr(__main__, "__compiled__", None) is not None:
            return True
    except Exception:
        pass
    return globals().get("__compiled__") is not None
