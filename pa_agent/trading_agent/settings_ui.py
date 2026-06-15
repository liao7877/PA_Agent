"""Trading Agent–specific settings UI (notification, MT5 path, tracking window)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from pa_agent.config.settings import Settings
    from pa_agent.gui.settings_dialog import SettingsDialog


class TradingAgentSettingsExtension:
    """Widgets and load/save for Trading Agent fields in SettingsDialog."""

    def __init__(self, dialog: SettingsDialog) -> None:
        self._dialog = dialog

    def install_general_fields(self, form: QFormLayout) -> None:
        self._mt5_terminal_path_edit = QLineEdit()
        self._mt5_terminal_path_edit.setPlaceholderText(
            "留空=自动；或填 MT5 目录 / terminal64.exe 完整路径"
        )
        self._mt5_terminal_path_edit.setToolTip(
            "本机装有多套 MT5 时，指定要连接的那一套。\n"
            "可填安装目录（程序会自动找 terminal64.exe），\n"
            "或直接填 terminal64.exe 的完整路径。"
        )
        form.addRow("MT5 终端路径:", self._mt5_terminal_path_edit)

        self._auto_resume_chart_check = QCheckBox("分析完成后自动恢复「图表实时更新」")
        self._auto_resume_chart_check.setToolTip(
            "若提交分析时「图表实时更新」为关闭，图表会冻结为已收盘 K 线；"
            "勾选后，分析结束（成功或流程已跑完）将自动重新开启「图表实时更新」，"
            "并重新显示最右侧未收盘空心 K 线。分析中保持开启时不受此项影响。演示模式不受影响。"
        )
        form.addRow("图表:", self._auto_resume_chart_check)

        self._keep_analysis_time_window_check = QCheckBox("仅在指定时段内持续跟踪")
        self._keep_analysis_time_window_check.setToolTip(
            "开启后，持续跟踪只在下方时段内自动提交分析；"
            "时段外若无持仓则暂停，进入时段后恢复。"
        )
        form.addRow("跟踪时段:", self._keep_analysis_time_window_check)

        tracking_time_row = QHBoxLayout()
        self._keep_analysis_time_start_edit = QTimeEdit()
        self._keep_analysis_time_start_edit.setDisplayFormat("HH:mm")
        tracking_time_row.addWidget(self._keep_analysis_time_start_edit)
        self._keep_analysis_time_sep_label = QLabel("至")
        tracking_time_row.addWidget(self._keep_analysis_time_sep_label)
        self._keep_analysis_time_end_edit = QTimeEdit()
        self._keep_analysis_time_end_edit.setDisplayFormat("HH:mm")
        tracking_time_row.addWidget(self._keep_analysis_time_end_edit)
        form.addRow("跟踪起止时间:", tracking_time_row)

        self._keep_analysis_time_hint_label = QLabel()
        self._keep_analysis_time_hint_label.setWordWrap(True)
        self._keep_analysis_time_hint_label.setStyleSheet(
            "color: #8b949e; font-size: 11px;"
        )
        form.addRow("", self._keep_analysis_time_hint_label)

        self._keep_analysis_bypass_position_check = QCheckBox("有持仓时不受跟踪时段限制")
        form.addRow("", self._keep_analysis_bypass_position_check)

        self._keep_analysis_time_window_check.toggled.connect(
            self._sync_keep_analysis_time_widgets_enabled
        )
        self._keep_analysis_time_start_edit.timeChanged.connect(
            self._update_keep_analysis_time_hint
        )
        self._keep_analysis_time_end_edit.timeChanged.connect(
            self._update_keep_analysis_time_hint
        )

    def install_notification_group(self, parent_layout: QVBoxLayout) -> None:
        notification_group = QGroupBox("通知")
        notification_form = QFormLayout(notification_group)

        self._notify_enabled_check = QCheckBox("启用通知（总开关）")
        self._notify_enabled_check.setToolTip(
            "开启后，分析决策与持仓事件将推送到下方配置的渠道。"
        )
        notification_form.addRow("启用:", self._notify_enabled_check)

        ding_row = QHBoxLayout()
        self._dingtalk_webhook_edit = QLineEdit()
        self._dingtalk_webhook_edit.setPlaceholderText("钉钉群机器人 Webhook URL")
        ding_row.addWidget(self._dingtalk_webhook_edit)
        show_ding_btn = QPushButton("隐藏")
        show_ding_btn.setCheckable(True)
        show_ding_btn.setFixedWidth(52)
        show_ding_btn.toggled.connect(
            lambda checked: self._dingtalk_webhook_edit.setEchoMode(
                QLineEdit.EchoMode.Password if checked else QLineEdit.EchoMode.Normal
            )
        )
        ding_row.addWidget(show_ding_btn)
        notification_form.addRow("钉钉 Webhook:", ding_row)

        self._dingtalk_secret_edit = QLineEdit()
        self._dingtalk_secret_edit.setPlaceholderText("可选：加签 Secret")
        self._dingtalk_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        notification_form.addRow("钉钉加签 Secret:", self._dingtalk_secret_edit)

        wechat_row = QHBoxLayout()
        self._wechat_webhook_edit = QLineEdit()
        self._wechat_webhook_edit.setPlaceholderText("Bark / Server酱 / 企业微信 Webhook")
        wechat_row.addWidget(self._wechat_webhook_edit)
        show_wechat_btn = QPushButton("隐藏")
        show_wechat_btn.setCheckable(True)
        show_wechat_btn.setFixedWidth(52)
        show_wechat_btn.toggled.connect(
            lambda checked: self._wechat_webhook_edit.setEchoMode(
                QLineEdit.EchoMode.Password if checked else QLineEdit.EchoMode.Normal
            )
        )
        wechat_row.addWidget(show_wechat_btn)
        notification_form.addRow("微信 Webhook:", wechat_row)

        self._notify_new_order_check = QCheckBox("产生新的下单决策（入场/止盈/止损）")
        notification_form.addRow("场景 · 新下单:", self._notify_new_order_check)

        self._notify_entry_filled_check = QCheckBox("计划单被触及、确认入场成交")
        notification_form.addRow("场景 · 入场成交:", self._notify_entry_filled_check)

        self._notify_exit_check = QCheckBox("持仓出场（止盈/止损/AI 平仓）")
        notification_form.addRow("场景 · 出场:", self._notify_exit_check)

        self._notify_manage_check = QCheckBox("持仓管理调整（移动止盈/止损）")
        notification_form.addRow("场景 · 持仓调整:", self._notify_manage_check)

        self._notify_no_trade_check = QCheckBox("观望/不下单结论也通知")
        notification_form.addRow("场景 · 观望:", self._notify_no_trade_check)

        self._notify_error_check = QCheckBox("分析失败/异常时通知")
        notification_form.addRow("场景 · 异常:", self._notify_error_check)

        self._notify_api_error_check = QCheckBox("API 调用异常时通知（网络/鉴权/限流等）")
        notification_form.addRow("场景 · API 异常:", self._notify_api_error_check)

        self._notify_timeout_spin = QSpinBox()
        self._notify_timeout_spin.setRange(3, 120)
        self._notify_timeout_spin.setSuffix(" s")
        notification_form.addRow("请求超时:", self._notify_timeout_spin)

        notify_test_btn = QPushButton("发送测试通知")
        notify_test_btn.setToolTip("使用当前填写的 Webhook 发送一条测试消息（无需保存）")
        notify_test_btn.clicked.connect(self._on_send_test_notification)
        notification_form.addRow("", notify_test_btn)

        parent_layout.addWidget(notification_group)

    def load(self, settings: Settings) -> None:
        g = settings.general
        self._mt5_terminal_path_edit.setText(getattr(g, "mt5_terminal_path", "") or "")
        self._auto_resume_chart_check.setChecked(
            bool(getattr(g, "auto_resume_chart_after_analysis", False))
        )
        self._keep_analysis_time_window_check.setChecked(
            bool(getattr(g, "keep_analysis_time_window_enabled", False))
        )
        from pa_agent.config.tracking_schedule import parse_hhmm

        start_h, start_m = parse_hhmm(
            getattr(g, "keep_analysis_time_start", "09:00"), default=(9, 0)
        )
        end_h, end_m = parse_hhmm(
            getattr(g, "keep_analysis_time_end", "23:00"), default=(23, 0)
        )
        self._keep_analysis_time_start_edit.setTime(QTime(start_h, start_m))
        self._keep_analysis_time_end_edit.setTime(QTime(end_h, end_m))
        self._keep_analysis_bypass_position_check.setChecked(
            bool(getattr(g, "keep_analysis_bypass_with_position", True))
        )
        self._sync_keep_analysis_time_widgets_enabled()
        self._update_keep_analysis_time_hint()

        n = getattr(settings, "notification", None)
        if n is not None:
            self._notify_enabled_check.setChecked(bool(getattr(n, "enabled", False)))
            self._dingtalk_webhook_edit.setText(getattr(n, "dingtalk_webhook", "") or "")
            self._dingtalk_secret_edit.setText(getattr(n, "dingtalk_secret", "") or "")
            self._wechat_webhook_edit.setText(getattr(n, "wechat_webhook", "") or "")
            self._notify_new_order_check.setChecked(
                bool(getattr(n, "notify_new_order", True))
            )
            self._notify_entry_filled_check.setChecked(
                bool(getattr(n, "notify_entry_filled", True))
            )
            self._notify_exit_check.setChecked(bool(getattr(n, "notify_exit", True)))
            self._notify_manage_check.setChecked(bool(getattr(n, "notify_manage", True)))
            self._notify_no_trade_check.setChecked(
                bool(getattr(n, "notify_no_trade", False))
            )
            self._notify_error_check.setChecked(bool(getattr(n, "notify_error", False)))
            self._notify_api_error_check.setChecked(
                bool(getattr(n, "notify_api_error", False))
            )
            self._notify_timeout_spin.setValue(
                int(getattr(n, "request_timeout_s", 10) or 10)
            )

    def save(self, settings: Settings) -> None:
        g = settings.general
        g.mt5_terminal_path = self._mt5_terminal_path_edit.text().strip()
        g.auto_resume_chart_after_analysis = self._auto_resume_chart_check.isChecked()
        g.keep_analysis_time_window_enabled = (
            self._keep_analysis_time_window_check.isChecked()
        )
        g.keep_analysis_time_start = (
            self._keep_analysis_time_start_edit.time().toString("HH:mm")
        )
        g.keep_analysis_time_end = self._keep_analysis_time_end_edit.time().toString(
            "HH:mm"
        )
        g.keep_analysis_bypass_with_position = (
            self._keep_analysis_bypass_position_check.isChecked()
        )
        n = getattr(settings, "notification", None)
        if n is None:
            return
        n.enabled = self._notify_enabled_check.isChecked()
        n.dingtalk_webhook = self._dingtalk_webhook_edit.text().strip()
        n.dingtalk_secret = self._dingtalk_secret_edit.text().strip()
        n.wechat_webhook = self._wechat_webhook_edit.text().strip()
        n.notify_new_order = self._notify_new_order_check.isChecked()
        n.notify_entry_filled = self._notify_entry_filled_check.isChecked()
        n.notify_exit = self._notify_exit_check.isChecked()
        n.notify_manage = self._notify_manage_check.isChecked()
        n.notify_no_trade = self._notify_no_trade_check.isChecked()
        n.notify_error = self._notify_error_check.isChecked()
        n.notify_api_error = self._notify_api_error_check.isChecked()
        n.request_timeout_s = self._notify_timeout_spin.value()

    def _sync_keep_analysis_time_widgets_enabled(self, *_args: Any) -> None:
        enabled = self._keep_analysis_time_window_check.isChecked()
        self._keep_analysis_time_start_edit.setEnabled(enabled)
        self._keep_analysis_time_end_edit.setEnabled(enabled)
        self._keep_analysis_bypass_position_check.setEnabled(enabled)
        self._keep_analysis_time_hint_label.setEnabled(enabled)

    def _update_keep_analysis_time_hint(self, *_args: Any) -> None:
        from pa_agent.config.tracking_schedule import (
            format_tracking_window_hint,
            is_overnight_window,
        )

        start = self._keep_analysis_time_start_edit.time().toString("HH:mm")
        end = self._keep_analysis_time_end_edit.time().toString("HH:mm")
        overnight = is_overnight_window(start, end)
        self._keep_analysis_time_sep_label.setText("至次日" if overnight else "至")
        dialog = self._dialog
        data_source = None
        parent = dialog.parent()
        if parent is not None:
            ctx = getattr(parent, "_ctx", None)
            if ctx is not None:
                data_source = getattr(ctx, "data_source", None)
        self._keep_analysis_time_hint_label.setText(
            format_tracking_window_hint(start, end, data_source=data_source)
        )

    def _on_send_test_notification(self) -> None:
        self.save(self._dialog._settings)  # noqa: SLF001
        n = getattr(self._dialog._settings, "notification", None)  # noqa: SLF001
        if n is None:
            return
        from pa_agent.notification.channels import DingTalkChannel, WeChatChannel
        from pa_agent.notification.events import NotificationEvent, NotificationMessage

        message = NotificationMessage(
            event=NotificationEvent.NEW_ORDER,
            title="🔔 Trading Agent 测试通知",
            text="这是一条来自 Trading Agent 的测试消息。\n若你收到它，说明通知渠道配置正确。",
            plain_text="Trading Agent 测试通知：渠道配置正确。",
        )
        timeout = int(getattr(n, "request_timeout_s", 10) or 10)
        channels = []
        ding = (getattr(n, "dingtalk_webhook", "") or "").strip()
        if ding:
            channels.append(
                DingTalkChannel(
                    webhook=ding,
                    secret=(getattr(n, "dingtalk_secret", "") or "").strip(),
                    timeout_s=timeout,
                )
            )
        wechat = (getattr(n, "wechat_webhook", "") or "").strip()
        if wechat:
            channels.append(WeChatChannel(webhook=wechat, timeout_s=timeout))
        if not channels:
            QMessageBox.warning(self._dialog, "测试通知", "请先填写至少一个 Webhook 地址。")
            return
        errors: list[str] = []
        for channel in channels:
            result = channel.send(message)
            if not result.ok:
                errors.append(f"{channel.name}: {result.error or result.status}")
        if errors:
            QMessageBox.warning(
                self._dialog, "测试通知", "发送失败：\n" + "\n".join(errors)
            )
        else:
            QMessageBox.information(
                self._dialog, "测试通知", "测试消息已发送，请检查手机/群消息。"
            )
