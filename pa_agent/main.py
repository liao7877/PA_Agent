"""Application entry point — delegates to Trading Agent product layer."""
from __future__ import annotations

from pa_agent.trading_agent.entry import main

__all__ = ["main"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
