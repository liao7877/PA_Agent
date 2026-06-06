"""Overlay horizontal lines for entry / TP / SL on a pyqtgraph PlotWidget."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pyqtgraph as pg
from PyQt6.QtGui import QColor

if TYPE_CHECKING:
    pass

# Line colors
_COLOR_ENTRY = QColor(30, 144, 255)   # dodger blue
_COLOR_TP = QColor(0, 200, 80)        # green
_COLOR_SL = QColor(220, 50, 50)       # red

# Label offset above the line (in price units)
_LABEL_OFFSET = 0.0


class OverlayLines:
    """Manages entry / TP / SL horizontal lines on a PlotWidget.

    Each line is an ``pg.InfiniteLine`` (angle=0, i.e. horizontal) paired
    with a ``pg.TextItem`` label.

    Usage::

        overlay = OverlayLines()
        overlay.set_lines(plot_widget, entry=1900.0, tp=1920.0, sl=1880.0)
        # … later …
        overlay.clear_lines(plot_widget)
    """

    def __init__(self) -> None:
        self._items: list[pg.GraphicsItem] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def set_lines(
        self,
        plot_widget: pg.PlotWidget,
        entry: float,
        tp: float,
        sl: float,
        *,
        solid: bool = False,
        label_prefix: str = "",
        width: int = 1,
    ) -> None:
        """Draw (or redraw) the three horizontal price lines.

        Clears any previously drawn lines first.

        Parameters
        ----------
        solid:
            Use a solid pen (used for *held* positions) instead of dashed
            (used for *planned* order previews).
        label_prefix:
            Prepended to each line label, e.g. ``"持仓"``.
        width:
            Pen width in px.
        """
        self.clear_lines(plot_widget)

        specs = [
            (entry, _COLOR_ENTRY, "Entry"),
            (tp, _COLOR_TP, "TP"),
            (sl, _COLOR_SL, "SL"),
        ]

        style = pg.QtCore.Qt.PenStyle.SolidLine if solid else pg.QtCore.Qt.PenStyle.DashLine

        for price, color, label_text in specs:
            if price is None:
                continue
            line = pg.InfiniteLine(
                pos=price,
                angle=0,
                pen=pg.mkPen(color=color, width=width, style=style),
                movable=False,
            )
            prefix = f"{label_prefix} " if label_prefix else ""
            label = pg.TextItem(
                text=f"{prefix}{label_text}: {price:.5g}",
                color=color,
                anchor=(0.0, 1.0),
            )
            label.setPos(0, price)

            plot_widget.addItem(line)
            plot_widget.addItem(label)
            self._items.extend([line, label])

    def clear_lines(self, plot_widget: pg.PlotWidget) -> None:
        """Remove all managed lines and labels from the plot."""
        for item in self._items:
            plot_widget.removeItem(item)
        self._items.clear()
