"""TradingView-style instrument watchlist settings dialog."""
from __future__ import annotations

import copy
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pa_agent.config.settings import InstrumentSettings, Settings, save_settings
from pa_agent.data.factory import DATA_SOURCE_CHOICES, normalize_data_source_kind
from pa_agent.instruments import instrument_key


class InstrumentSettingsDialog(QDialog):
    """Edit the background monitored instruments list."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("多品种监控设置")
        self.setMinimumSize(900, 620)
        self._settings = settings
        self._items: list[InstrumentSettings] = [copy.deepcopy(x) for x in settings.instruments.items]
        if not self._items:
            self._items.append(InstrumentSettings())
        self._current_index = 0
        self._loading = False
        self._setup_ui()
        self._reload_list()
        self._load_current()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        hint = QLabel("左侧类似 TradingView Watchlist；启用的品种会在后台同时刷新并按持续跟踪设置自动分析。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e; font-size: 11px;")
        root.addWidget(hint)

        body = QHBoxLayout()
        root.addLayout(body, stretch=1)

        left = QVBoxLayout()
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self._list, stretch=1)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("新增")
        self._copy_btn = QPushButton("复制")
        self._delete_btn = QPushButton("删除")
        self._add_btn.clicked.connect(self._add_item)
        self._copy_btn.clicked.connect(self._copy_item)
        self._delete_btn.clicked.connect(self._delete_item)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._copy_btn)
        btn_row.addWidget(self._delete_btn)
        left.addLayout(btn_row)
        body.addLayout(left, stretch=1)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_basic_tab(), "基础")
        self._tabs.addTab(self._build_ai_tab(), "AI 覆盖")
        self._tabs.addTab(self._build_notify_tab(), "通知覆盖")
        body.addWidget(self._tabs, stretch=3)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setText("保存")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_basic_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self._enabled_check = QCheckBox("启用后台监控")
        self._name_edit = QLineEdit()
        self._symbol_edit = QLineEdit()
        self._tf_combo = QComboBox()
        self._tf_combo.addItems(["1m", "5m", "15m", "30m", "1h", "4h", "1d"])
        self._data_source_combo = QComboBox()
        for kind, label in DATA_SOURCE_CHOICES:
            self._data_source_combo.addItem(label, kind)
        self._tv_exchange_edit = QLineEdit()
        self._tv_exchange_edit.setPlaceholderText("留空 = 自动")
        self._keep_analysis_check = QCheckBox("有新K线收盘时自动分析")
        form.addRow("启用:", self._enabled_check)
        form.addRow("显示名:", self._name_edit)
        form.addRow("品种:", self._symbol_edit)
        form.addRow("周期:", self._tf_combo)
        form.addRow("数据源:", self._data_source_combo)
        form.addRow("TradingView 交易所:", self._tv_exchange_edit)
        form.addRow("持续跟踪:", self._keep_analysis_check)
        self._connect_basic_signals()
        return tab

    def _build_ai_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._provider_override_check = QCheckBox("单独覆盖 AI API 设置（关闭时继承全局 AI 模型设置）")
        layout.addWidget(self._provider_override_check)
        group = QGroupBox("AI 提供商")
        form = QFormLayout(group)
        self._model_edit = QLineEdit()
        self._base_url_edit = QLineEdit()
        self._api_key_edit = QLineEdit()
        self._thinking_check = QCheckBox("启用 Thinking")
        self._reasoning_combo = QComboBox()
        self._reasoning_combo.addItems(["low", "medium", "high", "max"])
        self._context_spin = QSpinBox()
        self._context_spin.setRange(1_000, 2_000_000)
        self._context_spin.setSingleStep(1_000)
        form.addRow("模型:", self._model_edit)
        form.addRow("Base URL:", self._base_url_edit)
        form.addRow("API Key:", self._api_key_edit)
        form.addRow("Thinking:", self._thinking_check)
        form.addRow("Reasoning:", self._reasoning_combo)
        form.addRow("Context Window:", self._context_spin)
        layout.addWidget(group)
        layout.addStretch()
        self._provider_override_check.stateChanged.connect(self._save_current)
        for widget in (self._model_edit, self._base_url_edit, self._api_key_edit):
            widget.textChanged.connect(self._save_current)
        self._thinking_check.stateChanged.connect(self._save_current)
        self._reasoning_combo.currentIndexChanged.connect(self._save_current)
        self._context_spin.valueChanged.connect(self._save_current)
        return tab

    def _build_notify_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self._notification_override_check = QCheckBox("单独覆盖钉钉 / 微信通知（关闭时继承全局通知设置）")
        layout.addWidget(self._notification_override_check)
        ding_group = QGroupBox("钉钉 / 微信")
        ding_form = QFormLayout(ding_group)
        self._notify_enabled_check = QCheckBox("启用")
        self._dingtalk_webhook_edit = QLineEdit()
        self._dingtalk_secret_edit = QLineEdit()
        self._wechat_webhook_edit = QLineEdit()
        self._notify_new_order_check = QCheckBox("新下单")
        self._notify_entry_filled_check = QCheckBox("入场成交")
        self._notify_exit_check = QCheckBox("出场")
        self._notify_manage_check = QCheckBox("持仓调整")
        self._notify_no_trade_check = QCheckBox("观望也通知")
        self._notify_error_check = QCheckBox("分析异常")
        self._notify_api_error_check = QCheckBox("API 异常")
        self._notify_timeout_spin = QSpinBox()
        self._notify_timeout_spin.setRange(1, 120)
        self._notify_timeout_spin.setSuffix(" s")
        ding_form.addRow("启用:", self._notify_enabled_check)
        ding_form.addRow("钉钉 Webhook:", self._dingtalk_webhook_edit)
        ding_form.addRow("钉钉 Secret:", self._dingtalk_secret_edit)
        ding_form.addRow("微信 Webhook:", self._wechat_webhook_edit)
        ding_form.addRow("新下单:", self._notify_new_order_check)
        ding_form.addRow("入场成交:", self._notify_entry_filled_check)
        ding_form.addRow("出场:", self._notify_exit_check)
        ding_form.addRow("持仓调整:", self._notify_manage_check)
        ding_form.addRow("观望:", self._notify_no_trade_check)
        ding_form.addRow("异常:", self._notify_error_check)
        ding_form.addRow("API 异常:", self._notify_api_error_check)
        ding_form.addRow("超时:", self._notify_timeout_spin)
        layout.addWidget(ding_group)

        self._feishu_override_check = QCheckBox("单独覆盖飞书设置")
        layout.addWidget(self._feishu_override_check)
        feishu_group = QGroupBox("飞书")
        feishu_form = QFormLayout(feishu_group)
        self._feishu_enabled_check = QCheckBox("启用飞书")
        self._feishu_webhook_edit = QLineEdit()
        self._feishu_secret_edit = QLineEdit()
        self._feishu_order_only_check = QCheckBox("仅下单机会推送")
        feishu_form.addRow("启用:", self._feishu_enabled_check)
        feishu_form.addRow("Webhook:", self._feishu_webhook_edit)
        feishu_form.addRow("Secret:", self._feishu_secret_edit)
        feishu_form.addRow("仅下单:", self._feishu_order_only_check)
        layout.addWidget(feishu_group)

        self._pushplus_override_check = QCheckBox("单独覆盖 PushPlus 设置")
        layout.addWidget(self._pushplus_override_check)
        push_group = QGroupBox("PushPlus")
        push_form = QFormLayout(push_group)
        self._pushplus_enabled_check = QCheckBox("启用 PushPlus")
        self._pushplus_token_edit = QLineEdit()
        push_form.addRow("启用:", self._pushplus_enabled_check)
        push_form.addRow("Token:", self._pushplus_token_edit)
        layout.addWidget(push_group)
        layout.addStretch()
        self._connect_notify_signals()
        return tab

    def _connect_basic_signals(self) -> None:
        self._enabled_check.stateChanged.connect(self._save_current)
        self._name_edit.textChanged.connect(self._save_current)
        self._symbol_edit.textChanged.connect(self._save_current)
        self._tf_combo.currentIndexChanged.connect(self._save_current)
        self._data_source_combo.currentIndexChanged.connect(self._save_current)
        self._tv_exchange_edit.textChanged.connect(self._save_current)
        self._keep_analysis_check.stateChanged.connect(self._save_current)

    def _connect_notify_signals(self) -> None:
        checks = [
            self._notification_override_check, self._notify_enabled_check,
            self._notify_new_order_check, self._notify_entry_filled_check,
            self._notify_exit_check, self._notify_manage_check,
            self._notify_no_trade_check, self._notify_error_check,
            self._notify_api_error_check, self._feishu_override_check,
            self._feishu_enabled_check, self._feishu_order_only_check,
            self._pushplus_override_check, self._pushplus_enabled_check,
        ]
        for check in checks:
            check.stateChanged.connect(self._save_current)
        edits = [
            self._dingtalk_webhook_edit, self._dingtalk_secret_edit,
            self._wechat_webhook_edit, self._feishu_webhook_edit,
            self._feishu_secret_edit, self._pushplus_token_edit,
        ]
        for edit in edits:
            edit.textChanged.connect(self._save_current)
        self._notify_timeout_spin.valueChanged.connect(self._save_current)

    def _reload_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for item in self._items:
            list_item = QListWidgetItem(self._item_label(item))
            list_item.setData(Qt.ItemDataRole.UserRole, instrument_key(item))
            if not item.enabled:
                list_item.setForeground(Qt.GlobalColor.gray)
            self._list.addItem(list_item)
        self._list.setCurrentRow(min(self._current_index, max(0, len(self._items) - 1)))
        self._list.blockSignals(False)

    def _item_label(self, item: InstrumentSettings) -> str:
        state = "运行" if item.enabled else "停用"
        return f"{item.symbol}  {item.timeframe}\n{state} · {item.data_source}"

    def _current(self) -> InstrumentSettings | None:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]
        return None

    def _on_row_changed(self, row: int) -> None:
        self._save_current()
        if 0 <= row < len(self._items):
            self._current_index = row
            self._load_current()

    def _load_current(self) -> None:
        item = self._current()
        if item is None:
            return
        self._loading = True
        self._enabled_check.setChecked(item.enabled)
        self._name_edit.setText(item.name)
        self._symbol_edit.setText(item.symbol)
        self._tf_combo.setCurrentText(item.timeframe)
        ds_idx = self._data_source_combo.findData(item.data_source)
        self._data_source_combo.setCurrentIndex(max(0, ds_idx))
        self._tv_exchange_edit.setText(item.tradingview_exchange)
        self._keep_analysis_check.setChecked(item.keep_analysis)

        self._provider_override_check.setChecked(item.provider_override_enabled)
        self._model_edit.setText(item.provider.model)
        self._base_url_edit.setText(item.provider.base_url)
        self._api_key_edit.setText(item.provider.api_key)
        self._thinking_check.setChecked(item.provider.thinking)
        self._reasoning_combo.setCurrentText(item.provider.reasoning_effort)
        self._context_spin.setValue(item.provider.context_window)

        self._notification_override_check.setChecked(item.notification_override_enabled)
        n = item.notification
        self._notify_enabled_check.setChecked(n.enabled)
        self._dingtalk_webhook_edit.setText(n.dingtalk_webhook)
        self._dingtalk_secret_edit.setText(n.dingtalk_secret)
        self._wechat_webhook_edit.setText(n.wechat_webhook)
        self._notify_new_order_check.setChecked(n.notify_new_order)
        self._notify_entry_filled_check.setChecked(n.notify_entry_filled)
        self._notify_exit_check.setChecked(n.notify_exit)
        self._notify_manage_check.setChecked(n.notify_manage)
        self._notify_no_trade_check.setChecked(n.notify_no_trade)
        self._notify_error_check.setChecked(n.notify_error)
        self._notify_api_error_check.setChecked(n.notify_api_error)
        self._notify_timeout_spin.setValue(n.request_timeout_s)

        self._feishu_override_check.setChecked(item.feishu_override_enabled)
        self._feishu_enabled_check.setChecked(item.feishu.enabled)
        self._feishu_webhook_edit.setText(item.feishu.webhook_url)
        self._feishu_secret_edit.setText(item.feishu.secret)
        self._feishu_order_only_check.setChecked(item.feishu.notify_on_order_only)

        self._pushplus_override_check.setChecked(item.pushplus_override_enabled)
        self._pushplus_enabled_check.setChecked(item.pushplus.enabled)
        self._pushplus_token_edit.setText(item.pushplus.token)
        self._loading = False

    def _save_current(self) -> None:
        if self._loading:
            return
        item = self._current()
        if item is None:
            return
        item.enabled = self._enabled_check.isChecked()
        item.name = self._name_edit.text().strip()
        item.symbol = self._symbol_edit.text().strip() or "XAUUSDm"
        item.timeframe = self._tf_combo.currentText().strip() or "15m"
        item.data_source = normalize_data_source_kind(str(self._data_source_combo.currentData()))
        item.tradingview_exchange = self._tv_exchange_edit.text().strip()
        item.keep_analysis = self._keep_analysis_check.isChecked()
        item.id = instrument_key(item)

        item.provider_override_enabled = self._provider_override_check.isChecked()
        item.provider.model = self._model_edit.text().strip()
        item.provider.base_url = self._base_url_edit.text().strip()
        item.provider.api_key = self._api_key_edit.text().strip()
        item.provider.thinking = self._thinking_check.isChecked()
        item.provider.reasoning_effort = self._reasoning_combo.currentText()  # type: ignore[assignment]
        item.provider.context_window = self._context_spin.value()

        item.notification_override_enabled = self._notification_override_check.isChecked()
        n = item.notification
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

        item.feishu_override_enabled = self._feishu_override_check.isChecked()
        item.feishu.enabled = self._feishu_enabled_check.isChecked()
        item.feishu.webhook_url = self._feishu_webhook_edit.text().strip()
        item.feishu.secret = self._feishu_secret_edit.text().strip()
        item.feishu.notify_on_order_only = self._feishu_order_only_check.isChecked()

        item.pushplus_override_enabled = self._pushplus_override_check.isChecked()
        item.pushplus.enabled = self._pushplus_enabled_check.isChecked()
        item.pushplus.token = self._pushplus_token_edit.text().strip()
        row = self._list.currentRow()
        if row >= 0:
            self._list.item(row).setText(self._item_label(item))

    def _add_item(self) -> None:
        self._save_current()
        base = copy.deepcopy(self._settings.instruments.items[0] if self._settings.instruments.items else InstrumentSettings())
        base.symbol = ""
        base.name = ""
        base.id = "new-instrument"
        base.enabled = True
        base.keep_analysis = False
        self._items.append(base)
        self._current_index = len(self._items) - 1
        self._reload_list()
        self._load_current()
        self._symbol_edit.setFocus()

    def _copy_item(self) -> None:
        item = self._current()
        if item is None:
            return
        self._save_current()
        copied = copy.deepcopy(item)
        copied.name = f"{copied.name or copied.symbol} 副本"
        copied.id = f"{instrument_key(copied)}-copy"
        self._items.append(copied)
        self._current_index = len(self._items) - 1
        self._reload_list()
        self._load_current()

    def _delete_item(self) -> None:
        if len(self._items) <= 1:
            QMessageBox.information(self, "不能删除", "至少保留一个监控品种。")
            return
        row = self._current_index
        self._items.pop(row)
        self._current_index = max(0, row - 1)
        self._reload_list()
        self._load_current()

    def _on_save(self) -> None:
        self._save_current()
        cleaned = []
        seen = set()
        for item in self._items:
            item.symbol = item.symbol.strip()
            if not item.symbol:
                QMessageBox.warning(self, "品种不能为空", "请填写所有监控品种的品种代码。")
                return
            item.id = instrument_key(item)
            if item.id in seen:
                QMessageBox.warning(self, "品种重复", f"{item.symbol} {item.timeframe} 已重复。")
                return
            seen.add(item.id)
            cleaned.append(item)
        self._settings.instruments.items = cleaned
        save_settings(self._settings)
        self.accept()
