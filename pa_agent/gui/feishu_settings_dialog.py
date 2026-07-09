"""飞书机器人设置对话框.

提供 GUI 界面填写并保存到 config/settings.json 的 feishu 段。
包含：Webhook URL、签名密钥、企业自建应用 App ID / App Secret，
以及启用/禁用开关，并带有一键发送测试消息功能。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pa_agent.config.paths import SETTINGS_JSON_PATH
from pa_agent.config.settings import Settings, save_settings

logger = logging.getLogger(__name__)


class FeishuSettingsDialog(QDialog):
    """填写飞书机器人 Webhook 等配置的模态对话框."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("飞书机器人设置")
        self.setMinimumWidth(520)
        self._setup_ui()
        self._load_values()

    # ── UI 搭建 ───────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ── 状态开关 ───────────────────────────────────────────────────────────
        self._enabled_check = QCheckBox("启用飞书通知（下单信号推送到飞书群）")
        self._enabled_check.setToolTip(
            "关闭后即使有下单决策也不发送飞书消息，其余配置保留。"
        )
        root.addWidget(self._enabled_check)

        # ── 基础配置 ───────────────────────────────────────────────────────────
        basic_group = QGroupBox("自定义机器人（必填）")
        basic_form = QFormLayout(basic_group)
        basic_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._webhook_edit = QLineEdit()
        self._webhook_edit.setPlaceholderText(
            "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxx"
        )
        self._webhook_edit.setToolTip(
            "飞书群 → 右上角设置 → 群机器人 → 添加自定义机器人 → 复制 Webhook 地址"
        )
        basic_form.addRow("Webhook URL:", self._webhook_edit)

        secret_row = QHBoxLayout()
        self._secret_edit = QLineEdit()
        self._secret_edit.setPlaceholderText("留空则不启用签名校验")
        self._secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._secret_edit.setToolTip(
            "飞书自定义机器人安全设置 → 签名校验 → 复制密钥（可选，留空不校验）"
        )
        secret_row.addWidget(self._secret_edit)
        self._show_secret_btn = QPushButton("显示")
        self._show_secret_btn.setCheckable(True)
        self._show_secret_btn.setFixedWidth(52)
        self._show_secret_btn.toggled.connect(self._toggle_secret_visibility)
        secret_row.addWidget(self._show_secret_btn)
        basic_form.addRow("签名密钥（Secret）:", secret_row)

        root.addWidget(basic_group)

        # ── 图片上传（可选）────────────────────────────────────────────────────
        img_group = QGroupBox("企业自建应用（可选，用于发送 K 线图表截图）")
        img_form = QFormLayout(img_group)
        img_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        img_hint = QLabel(
            "需在飞书开放平台创建企业自建应用，申请 im:resource 权限后填写。\n"
            "未填写时发送纯文字卡片（无图表截图）。"
        )
        img_hint.setWordWrap(True)
        img_hint.setStyleSheet("color: #8b949e; font-size: 11px;")
        img_form.addRow(img_hint)

        self._app_id_edit = QLineEdit()
        self._app_id_edit.setPlaceholderText("cli_xxxxxxxxxxxxxxxx")
        img_form.addRow("App ID:", self._app_id_edit)

        app_secret_row = QHBoxLayout()
        self._app_secret_edit = QLineEdit()
        self._app_secret_edit.setPlaceholderText("企业自建应用的 App Secret")
        self._app_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        app_secret_row.addWidget(self._app_secret_edit)
        self._show_app_secret_btn = QPushButton("显示")
        self._show_app_secret_btn.setCheckable(True)
        self._show_app_secret_btn.setFixedWidth(52)
        self._show_app_secret_btn.toggled.connect(self._toggle_app_secret_visibility)
        app_secret_row.addWidget(self._show_app_secret_btn)
        img_form.addRow("App Secret:", app_secret_row)

        root.addWidget(img_group)

        ding_group = QGroupBox("钉钉 / 微信通知（可选）")
        ding_form = QFormLayout(ding_group)
        ding_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._notify_enabled_check = QCheckBox("启用钉钉 / 微信通知（总开关）")
        self._notify_enabled_check.setToolTip(
            "开启后，分析决策与持仓事件将推送到下方配置的渠道。"
        )
        ding_form.addRow("启用:", self._notify_enabled_check)

        dingtalk_row = QHBoxLayout()
        self._dingtalk_webhook_edit = QLineEdit()
        self._dingtalk_webhook_edit.setPlaceholderText("钉钉群机器人 Webhook URL")
        dingtalk_row.addWidget(self._dingtalk_webhook_edit)
        self._show_dingtalk_btn = QPushButton("隐藏")
        self._show_dingtalk_btn.setCheckable(True)
        self._show_dingtalk_btn.setFixedWidth(52)
        self._show_dingtalk_btn.toggled.connect(
            lambda checked: self._dingtalk_webhook_edit.setEchoMode(
                QLineEdit.EchoMode.Password if checked else QLineEdit.EchoMode.Normal
            )
        )
        dingtalk_row.addWidget(self._show_dingtalk_btn)
        ding_form.addRow("钉钉 Webhook:", dingtalk_row)

        self._dingtalk_secret_edit = QLineEdit()
        self._dingtalk_secret_edit.setPlaceholderText("可选：加签 Secret")
        self._dingtalk_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        ding_form.addRow("钉钉加签 Secret:", self._dingtalk_secret_edit)

        wechat_row = QHBoxLayout()
        self._wechat_webhook_edit = QLineEdit()
        self._wechat_webhook_edit.setPlaceholderText("Bark / Server酱 / 企业微信 Webhook")
        wechat_row.addWidget(self._wechat_webhook_edit)
        self._show_wechat_btn = QPushButton("隐藏")
        self._show_wechat_btn.setCheckable(True)
        self._show_wechat_btn.setFixedWidth(52)
        self._show_wechat_btn.toggled.connect(
            lambda checked: self._wechat_webhook_edit.setEchoMode(
                QLineEdit.EchoMode.Password if checked else QLineEdit.EchoMode.Normal
            )
        )
        wechat_row.addWidget(self._show_wechat_btn)
        ding_form.addRow("微信 Webhook:", wechat_row)

        self._notify_new_order_check = QCheckBox("产生新的下单决策（入场/止盈/止损）")
        ding_form.addRow("场景 · 新下单:", self._notify_new_order_check)

        self._notify_entry_filled_check = QCheckBox("计划单被触及、确认入场成交")
        ding_form.addRow("场景 · 入场成交:", self._notify_entry_filled_check)

        self._notify_exit_check = QCheckBox("持仓出场（止盈/止损/AI 平仓）")
        ding_form.addRow("场景 · 出场:", self._notify_exit_check)

        self._notify_manage_check = QCheckBox("持仓管理调整（移动止盈/止损）")
        ding_form.addRow("场景 · 持仓调整:", self._notify_manage_check)

        self._notify_no_trade_check = QCheckBox("观望/不下单结论也通知")
        ding_form.addRow("场景 · 观望:", self._notify_no_trade_check)

        self._notify_error_check = QCheckBox("分析失败/异常时通知")
        ding_form.addRow("场景 · 异常:", self._notify_error_check)

        self._notify_api_error_check = QCheckBox("API 调用异常时通知（网络/鉴权/限流等）")
        ding_form.addRow("场景 · API 异常:", self._notify_api_error_check)

        self._notify_timeout_spin = QSpinBox()
        self._notify_timeout_spin.setRange(3, 120)
        self._notify_timeout_spin.setSuffix(" s")
        ding_form.addRow("请求超时:", self._notify_timeout_spin)

        self._notify_test_btn = QPushButton("发送钉钉/微信测试通知")
        self._notify_test_btn.setToolTip("使用当前填写的 Webhook 发送一条测试消息（无需保存）")
        self._notify_test_btn.clicked.connect(self._on_test_notification)
        ding_form.addRow("", self._notify_test_btn)

        root.addWidget(ding_group)

        # ── 测试按钮 & 远程协助按钮 ──────────────────────────────────────────────
        test_row = QHBoxLayout()
        self._test_btn = QPushButton("发送测试消息")
        self._test_btn.setToolTip(
            "使用当前填写的配置向飞书群发送一条测试文本消息，验证 Webhook 是否正常。"
        )
        self._test_btn.clicked.connect(self._on_test)
        test_row.addWidget(self._test_btn)

        self._remote_help_btn = QPushButton("帮我远程协助设置")
        self._remote_help_btn.setStyleSheet(
            "QPushButton { font-size: 14pt; font-weight: bold; "
            "padding: 10px 20px; background-color: #4a90d9; color: white; "
            "border-radius: 6px; }"
            "QPushButton:hover { background-color: #357abd; }"
            "QPushButton:pressed { background-color: #2a5f9e; }"
        )
        self._remote_help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remote_help_btn.clicked.connect(self._on_remote_help)
        test_row.addWidget(self._remote_help_btn)
        test_row.addStretch()
        root.addLayout(test_row)

        # ── 确认 / 取消 ────────────────────────────────────────────────────────
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = btn_box.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("保存")
        cancel_btn = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

    # ── 加载 / 保存 ────────────────────────────────────────────────────────────

    def _load_values(self) -> None:
        cfg = self._settings.feishu
        self._enabled_check.setChecked(cfg.enabled)
        self._webhook_edit.setText(cfg.webhook_url)
        self._secret_edit.setText(cfg.secret)
        self._app_id_edit.setText(cfg.app_id)
        self._app_secret_edit.setText(cfg.app_secret)

        n = getattr(self._settings, "notification", None)
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

    def _apply_values_to_settings(self) -> None:
        feishu = self._settings.feishu
        feishu.enabled = self._enabled_check.isChecked()
        feishu.webhook_url = self._webhook_edit.text().strip()
        feishu.secret = self._secret_edit.text().strip()
        feishu.app_id = self._app_id_edit.text().strip()
        feishu.app_secret = self._app_secret_edit.text().strip()

        n = getattr(self._settings, "notification", None)
        if n is not None:
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

    def _on_save(self) -> None:
        self._apply_values_to_settings()
        if self._settings.feishu.enabled and not self._settings.feishu.webhook_url:
            QMessageBox.warning(
                self,
                "配置不完整",
                "已启用飞书通知，但 Webhook URL 为空。\n请填写 Webhook URL 或关闭启用开关。",
            )
            return
        try:
            save_settings(self._settings, SETTINGS_JSON_PATH)
            self.accept()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "保存失败",
                f"写入 config/settings.json 失败：\n{exc}",
            )

    # ── 显示 / 隐藏密钥 ───────────────────────────────────────────────────────

    def _toggle_secret_visibility(self, checked: bool) -> None:
        if checked:
            self._secret_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._show_secret_btn.setText("隐藏")
        else:
            self._secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._show_secret_btn.setText("显示")

    def _toggle_app_secret_visibility(self, checked: bool) -> None:
        if checked:
            self._app_secret_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._show_app_secret_btn.setText("隐藏")
        else:
            self._app_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._show_app_secret_btn.setText("显示")

    # ── 测试发送 ──────────────────────────────────────────────────────────────

    def _on_remote_help(self) -> None:
        """显示远程协助设置信息."""
        dlg = QDialog(self)
        dlg.setWindowTitle("远程协助设置")
        layout = QVBoxLayout(dlg)
        label = QLabel(
            "去问龙虾PA_Agent这个项目怎么使用飞书功能，一步一步教我<br>"
            "还是搞不定的话<br>"
            "可以联系阿尔法本人QQ：564020069<br><br>"
            "赞助49.9元可以帮你远程协助完成飞书设置<br><br>"
            "如果之前已经支付过49.9元了，这次只需要赞助30元即可"
        )
        label.setStyleSheet("font-size: 20pt; font-weight: bold;")
        label.setWordWrap(True)
        layout.addWidget(label)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(dlg.accept)
        layout.addWidget(bb)
        dlg.exec()

    def _on_test_notification(self) -> None:
        n = getattr(self._settings, "notification", None)
        if n is None:
            return
        webhook = self._dingtalk_webhook_edit.text().strip()
        secret = self._dingtalk_secret_edit.text().strip()
        wechat_webhook = self._wechat_webhook_edit.text().strip()
        timeout = int(self._notify_timeout_spin.value())

        from pa_agent.notification.channels import DingTalkChannel, WeChatChannel
        from pa_agent.notification.events import NotificationEvent, NotificationMessage

        message = NotificationMessage(
            event=NotificationEvent.NEW_ORDER,
            title="🔔 Trading Agent 测试通知",
            text="这是一条来自 Trading Agent 的测试消息。\n若你收到它，说明通知渠道配置正确。",
            plain_text="Trading Agent 测试通知：渠道配置正确。",
        )
        channels = []
        if webhook:
            channels.append(
                DingTalkChannel(
                    webhook=webhook,
                    secret=secret,
                    timeout_s=timeout,
                )
            )
        if wechat_webhook:
            channels.append(WeChatChannel(webhook=wechat_webhook, timeout_s=timeout))
        if not channels:
            QMessageBox.warning(self, "测试通知", "请先填写至少一个 Webhook 地址。")
            return
        errors: list[str] = []
        for channel in channels:
            result = channel.send(message)
            if not result.ok:
                errors.append(f"{channel.name}: {result.error or result.status}")
        if errors:
            QMessageBox.warning(self, "测试通知", "发送失败：\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "测试通知", "测试消息已发送，请检查手机/群消息。")

    def _on_test(self) -> None:
        """用当前表单填写的值向飞书群发送测试文本消息."""
        webhook_url = self._webhook_edit.text().strip()
        if not webhook_url:
            QMessageBox.warning(self, "缺少配置", "请先填写 Webhook URL 再测试。")
            return

        try:
            import requests  # type: ignore[import]
        except ImportError:
            QMessageBox.critical(
                self,
                "缺少依赖",
                "未安装 requests 库，请在终端运行：\npip install requests",
            )
            return

        payload: dict = {
            "msg_type": "text",
            "content": {"text": "✅ PA Agent 飞书通知测试消息，配置正常！"},
        }
        secret = self._secret_edit.text().strip()
        if secret:
            ts = int(time.time())
            string_to_sign = f"{ts}\n{secret}"
            hmac_code = hmac.new(
                string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
            ).digest()
            payload["timestamp"] = str(ts)
            payload["sign"] = base64.b64encode(hmac_code).decode("utf-8")

        try:
            resp = requests.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            result = resp.json()
        except Exception as exc:
            QMessageBox.critical(self, "发送失败", f"HTTP 请求失败：\n{exc}")
            return

        if result.get("code") == 0 or result.get("StatusCode") == 0:
            QMessageBox.information(
                self,
                "发送成功",
                "测试消息已成功发送到飞书群，请查收！\n\n"
                "（注意：图表截图功能需要额外配置企业自建应用）",
            )
        else:
            code = result.get("code", result.get("StatusCode", "?"))
            msg = result.get("msg", result.get("StatusMessage", ""))
            hint = ""
            if code == 19021:
                hint = "\n\n原因：签名校验失败，请检查密钥是否正确或留空禁用签名。"
            elif code == 19024:
                hint = "\n\n原因：关键词校验失败，请检查机器人的自定义关键词设置。"
            elif code == 19022:
                hint = "\n\n原因：IP 校验失败，当前 IP 不在白名单内。"
            QMessageBox.warning(
                self,
                "发送失败",
                f"飞书返回错误 code={code}，msg={msg}{hint}",
            )
