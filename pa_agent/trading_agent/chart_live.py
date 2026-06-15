"""Chart live-update toggle — isolated from main_window merge surface."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QHBoxLayout, QPushButton


class ChartLiveController:
    """Manages the checkable「图表实时更新」control and pause/resume semantics."""

    def __init__(self, window: Any) -> None:
        self._w = window

    def install_button(self, layout: QHBoxLayout) -> QPushButton:
        btn = QPushButton("图表实时更新")
        btn.setCheckable(True)
        btn.setChecked(True)
        btn.setToolTip(
            "开关：开启后图表持续刷新，最右侧未收盘 K 线为浅色空心 K 线（不参与 AI 分析）；"
            "分析进行中也可保持开启，不影响未完成 K 线显示"
        )
        btn.toggled.connect(self.on_toggle)
        layout.addWidget(btn)
        self._w._resume_chart_btn = btn  # noqa: SLF001
        return btn

    @property
    def paused(self) -> bool:
        return bool(getattr(self._w, "_chart_refresh_paused", False))

    @paused.setter
    def paused(self, value: bool) -> None:
        self._w._chart_refresh_paused = value  # noqa: SLF001
        btn = getattr(self._w, "_resume_chart_btn", None)
        if btn is not None:
            btn.blockSignals(True)
            btn.setChecked(not value)
            btn.blockSignals(False)

    def enabled(self) -> bool:
        return not self.paused

    def wants_forming_bar(self) -> bool:
        return self.enabled()

    def on_toggle(self, enabled: bool) -> None:
        if enabled:
            if self.paused:
                self._w._refresh_keep_analysis_sentinel()  # noqa: SLF001
            self.paused = False
            self._w._status_bar.showMessage("图表实时更新已开启")  # noqa: SLF001
            self._w._refresh_chart_once()  # noqa: SLF001
            return

        self.paused = True
        frame = self._w._pull_chart_frame_from_source(include_forming=False)  # noqa: SLF001
        chart = getattr(self._w, "_chart_widget", None)
        if frame is not None and chart is not None:
            chart.set_frame_now(frame)
        self._w._status_bar.showMessage("图表实时更新已关闭")  # noqa: SLF001
        self._w._update_refresh_elapsed()  # noqa: SLF001

    def auto_resume_after_analysis_enabled(self) -> bool:
        settings = getattr(self._w._ctx, "settings", None)  # noqa: SLF001
        if settings is None:
            return True
        return bool(getattr(settings.general, "auto_resume_chart_after_analysis", False))

    def maybe_auto_resume_after_analysis(self) -> bool:
        if getattr(self._w, "_demo_mode", False):  # noqa: SLF001
            return False
        if not self.auto_resume_after_analysis_enabled():
            return False
        if not self.paused:
            return False
        self.paused = False
        self._w._refresh_chart_once()  # noqa: SLF001
        return True

    def on_analysis_start(self, analysis_frame: Any) -> bool:
        """Freeze chart when live updates are off. Returns live_on."""
        live_on = self.enabled()
        if not live_on:
            self._w._chart_widget.set_frame_now(analysis_frame, fit_view=True)  # noqa: SLF001
            self.paused = True
        return live_on

    def status_hint(self) -> str:
        return "图表实时更新已开启" if self.enabled() else "图表已冻结"

    def apply_followup_snapshot(
        self,
        *,
        display_frame: Any,
        export_frame: Any,
        chart: Any,
        last_refresh_ts_setter: Any,
    ) -> None:
        """Refresh/freeze chart before follow-up; export table stays closed-only."""
        import time as _time

        live_on = self.enabled()
        if not live_on and display_frame is not None and chart is not None:
            from pa_agent.data.snapshot import frame_is_pure_closed, frames_equal_for_chart

            current = chart.displayed_frame()
            if not (
                export_frame is not None
                and current is not None
                and frame_is_pure_closed(current)
                and frames_equal_for_chart(current, export_frame)
            ):
                chart.set_frame_now(export_frame or display_frame)
            last_refresh_ts_setter(_time.monotonic())
        elif chart is not None and not live_on:
            display_frame = chart.displayed_frame()
            export_frame = display_frame

        if not live_on:
            self.paused = True
            self._w._update_refresh_elapsed()  # noqa: SLF001
            if getattr(self._w, "_status_bar", None) is not None:  # noqa: SLF001
                self._w._status_bar.showMessage(  # noqa: SLF001
                    "追问：已刷新并冻结图表，K线与屏幕一致"
                )
        elif getattr(self._w, "_status_bar", None) is not None:  # noqa: SLF001
            self._w._status_bar.showMessage("追问：已提交（图表实时更新保持开启）")  # noqa: SLF001
