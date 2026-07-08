"""Settings dialog for Trading Agent — edits all Settings fields via a form."""
from __future__ import annotations

from collections.abc import Callable

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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QTime, Qt, QUrl
from PyQt6.QtGui import QDesktopServices

from pa_agent.config.settings import Settings, save_settings
from pa_agent.config.paths import SETTINGS_JSON_PATH

_API_KEY_HELP_URL = "https://my.feishu.cn/wiki/CUV1wUKWxiQGhekQdRvcZQQ2ncf"
_AGENT_TUTORIAL_URL = (
    "https://my.feishu.cn/wiki/BEdFwGJhaiATbukuD2HccSXCnrb?from=from_copylink"
)


class SettingsDialog(QDialog):
    """Modal dialog that exposes all Settings fields as editable form widgets."""

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        data_source: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)
        self._settings = settings
        self._data_source = data_source
        self._setup_ui()
        self._load_values()

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        form_layout = QVBoxLayout(container)
        form_layout.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(container)
        root_layout.addWidget(scroll)

        provider_group = QGroupBox("AI 提供商")
        provider_form = QFormLayout(provider_group)

        self._model_edit = QLineEdit()
        provider_form.addRow("模型 (model):", self._model_edit)

        self._base_url_edit = QLineEdit()
        provider_form.addRow("Base URL:", self._base_url_edit)

        api_key_row = QHBoxLayout()
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("输入 API Key")
        api_key_row.addWidget(self._api_key_edit)
        self._show_key_btn = QPushButton("显示")
        self._show_key_btn.setCheckable(True)
        self._show_key_btn.setFixedWidth(52)
        self._show_key_btn.toggled.connect(self._toggle_api_key_visibility)
        api_key_row.addWidget(self._show_key_btn)
        provider_form.addRow("API Key:", api_key_row)

        self._thinking_check = QCheckBox("启用 Thinking")
        provider_form.addRow("Thinking:", self._thinking_check)

        self._reasoning_effort_combo = QComboBox()
        self._reasoning_effort_combo.addItems(["low", "medium", "high", "max"])
        self._reasoning_effort_combo.setToolTip(
            "思考强度。GPT-5.5 / o 系列会映射为 OpenAI reasoning_effort："
            "low / medium / high / xhigh（max→xhigh）；关闭 Thinking 时发送 none。"
        )
        provider_form.addRow("Reasoning Effort:", self._reasoning_effort_combo)

        self._context_window_spin = QSpinBox()
        self._context_window_spin.setRange(1_000, 2_000_000)
        self._context_window_spin.setSingleStep(1_000)
        provider_form.addRow("Context Window:", self._context_window_spin)

        self._api_health_btn = QPushButton("检测 API 连通性")
        self._api_health_btn.setToolTip(
            "使用当前表单中的模型、Base URL、API Key 发送一次最小请求，验证中转站/上游是否可用。"
        )
        self._api_health_btn.clicked.connect(self._on_check_api_health)
        provider_form.addRow("", self._api_health_btn)

        self._api_key_help_btn = QPushButton("点击获取模型API KEY")
        self._api_key_help_btn.setToolTip(_API_KEY_HELP_URL)
        self._api_key_help_btn.clicked.connect(self._open_api_key_help_url)
        provider_form.addRow("", self._api_key_help_btn)

        self._agent_tutorial_btn = QPushButton("智能体使用教程及问题解决方法")
        self._agent_tutorial_btn.setToolTip(_AGENT_TUTORIAL_URL)
        self._agent_tutorial_btn.clicked.connect(self._open_agent_tutorial_url)
        provider_form.addRow("", self._agent_tutorial_btn)

        form_layout.addWidget(provider_group)

        general_group = QGroupBox("通用设置")
        general_form = QFormLayout(general_group)

        self._analysis_bar_count_spin = QSpinBox()
        self._analysis_bar_count_spin.setRange(20, 5_000)
        self._analysis_bar_count_spin.setToolTip(
            "提交 AI 分析时使用的已收盘 K 线根数（不含当前未收盘 K 线）。"
            "程序要求至少 20 根已收盘 K 线才能分析。"
            "图表实时刷新也会按此数量拉取显示。"
        )
        general_form.addRow("用于分析的 K 线数量:", self._analysis_bar_count_spin)

        self._refresh_interval_spin = QSpinBox()
        self._refresh_interval_spin.setRange(100, 10_000)
        self._refresh_interval_spin.setSuffix(" ms")
        general_form.addRow("刷新间隔:", self._refresh_interval_spin)

        self._mt5_terminal_path_edit = QLineEdit()
        self._mt5_terminal_path_edit.setPlaceholderText(
            "留空=自动；或填 MT5 目录 / terminal64.exe 完整路径"
        )
        self._mt5_terminal_path_edit.setToolTip(
            "本机装有多套 MT5 时，指定要连接的那一套。\n"
            "可填安装目录（程序会自动找 terminal64.exe），\n"
            "或填完整路径，例如：\n"
            "D:\\BrokerA\\MetaTrader 5\\terminal64.exe\n"
            "修改后请重启程序，或切换一次数据来源以重新连接。"
        )
        general_form.addRow("MT5 终端路径:", self._mt5_terminal_path_edit)

        self._auto_resume_chart_check = QCheckBox("分析完成后自动恢复「图表实时更新」")
        self._auto_resume_chart_check.setToolTip(
            "提交分析时图表会暂停刷新并冻结为已收盘 K 线；"
            "勾选后，分析结束（成功或校验失败但流程已跑完）将自动恢复实时刷新，"
            "并重新显示最右侧未收盘空心 K 线。演示模式不受影响。"
        )
        general_form.addRow("图表:", self._auto_resume_chart_check)

        self._keep_analysis_check = QCheckBox("有新K线收盘时自动开始新一轮分析")
        self._keep_analysis_check.setToolTip(
            "勾选后，每当有新的K线收盘时自动触发分析（与主界面「持续跟踪分析」勾选框同步）"
        )
        general_form.addRow("持续跟踪分析:", self._keep_analysis_check)

        self._keep_analysis_time_window_check = QCheckBox("仅在指定时段内持续跟踪")
        self._keep_analysis_time_window_check.setToolTip(
            "开启后，持续跟踪只在下方时段内自动提交分析；"
            "时段外若无持仓则暂停跟踪，进入时段时会根据 K 线与上次分析能否衔接，"
            "自动选择完整分析或增量分析。\n"
            "支持跨午夜：开始时间晚于结束时间即表示到次日，"
            "例如 08:00 至 02:00 = 早上 8 点到次日凌晨 2 点。"
        )
        general_form.addRow("跟踪时段:", self._keep_analysis_time_window_check)

        tracking_time_row = QHBoxLayout()
        self._keep_analysis_time_start_edit = QTimeEdit()
        self._keep_analysis_time_start_edit.setDisplayFormat("HH:mm")
        self._keep_analysis_time_start_edit.setToolTip(
            "跟踪开始时刻（按本机当地时区填写，程序会自动检测并换算 MT5 经纪商时钟）。\n"
            "若开始晚于结束，表示跨到次日，如 08:00 开始、02:00 结束 = 至次日凌晨 2 点。"
        )
        tracking_time_row.addWidget(self._keep_analysis_time_start_edit)
        self._keep_analysis_time_sep_label = QLabel("至")
        tracking_time_row.addWidget(self._keep_analysis_time_sep_label)
        self._keep_analysis_time_end_edit = QTimeEdit()
        self._keep_analysis_time_end_edit.setDisplayFormat("HH:mm")
        self._keep_analysis_time_end_edit.setToolTip(
            "跟踪结束时刻（不含该分钟，本机当地时区）。\n"
            "结束早于开始时表示次日，例如 08:00 至 02:00："
            "当天 08:00 起跟踪，次日 02:00 前停止（02:00 起算时段外）。"
        )
        tracking_time_row.addWidget(self._keep_analysis_time_end_edit)
        general_form.addRow("跟踪起止时间:", tracking_time_row)

        self._keep_analysis_time_hint_label = QLabel()
        self._keep_analysis_time_hint_label.setWordWrap(True)
        self._keep_analysis_time_hint_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        general_form.addRow("", self._keep_analysis_time_hint_label)

        self._keep_analysis_bypass_position_check = QCheckBox(
            "有持仓时不受跟踪时段限制"
        )
        self._keep_analysis_bypass_position_check.setToolTip(
            "勾选后，只要软件持仓跟踪中有活跃持仓，时段外仍会在 K 线收盘时自动分析"
        )
        general_form.addRow("", self._keep_analysis_bypass_position_check)

        self._context_warning_spin = QSpinBox()
        self._context_warning_spin.setRange(1, 100)
        self._context_warning_spin.setSuffix(" %")
        general_form.addRow("上下文警告阈值:", self._context_warning_spin)

        self._stream_font_spin = QSpinBox()
        self._stream_font_spin.setRange(8, 28)
        self._stream_font_spin.setSuffix(" pt")
        self._stream_font_spin.setToolTip(
            "「实时」标签页中思考过程/撰写回答大文本框，以及下方追问输入框的字体大小"
        )
        general_form.addRow("实时窗口字号:", self._stream_font_spin)

        self._chart_seq_font_spin = QSpinBox()
        self._chart_seq_font_spin.setRange(6, 24)
        self._chart_seq_font_spin.setSuffix(" pt")
        self._chart_seq_font_spin.setToolTip("K 线图上 #1、#3… 序号标签的字体大小")
        general_form.addRow("图表K线序号字号:", self._chart_seq_font_spin)

        self._incremental_max_new_bars_spin = QSpinBox()
        self._incremental_max_new_bars_spin.setRange(0, 500)
        self._incremental_max_new_bars_spin.setSuffix(" 根")
        self._incremental_max_new_bars_spin.setToolTip(
            "同品种同周期下，若相对上一条成功记录只新增不超过该数量的已收盘K线，"
            "提交分析时走增量分析；设为 0 可关闭增量分析。"
        )
        general_form.addRow("增量分析最大新增K线:", self._incremental_max_new_bars_spin)

        self._decision_stance_combo = QComboBox()
        self._decision_stance_combo.addItem("保守", "conservative")
        self._decision_stance_combo.addItem("均衡（默认，比保守更愿意下单）", "balanced")
        self._decision_stance_combo.addItem("激进（比均衡更愿意下单）", "aggressive")
        self._decision_stance_combo.addItem(
            "极度激进（强制选方向与进场方式）",
            "extreme_aggressive",
        )
        self._decision_stance_combo.setToolTip(
            "仅影响阶段二交易决策倾向；保守与改版前一致。"
            "均衡、激进逐级提高下单意愿；极度激进在未触犯 §14 硬性禁止时"
            "必须给出具体做多/做空及限价/突破/市价方案。"
        )
        general_form.addRow("交易倾向:", self._decision_stance_combo)

        self._last_symbol_edit = QLineEdit()
        general_form.addRow("上次品种:", self._last_symbol_edit)

        self._last_timeframe_edit = QLineEdit()
        general_form.addRow("上次周期:", self._last_timeframe_edit)

        self._flow_auto_play_check = QCheckBox("决策树可视化生成后自动播放路径")
        general_form.addRow("决策树播放:", self._flow_auto_play_check)

        self._flow_play_seconds_spin = QSpinBox()
        self._flow_play_seconds_spin.setRange(3, 120)
        self._flow_play_seconds_spin.setSuffix(" 秒")
        general_form.addRow("播放时长:", self._flow_play_seconds_spin)

        self._flow_default_zoom_spin = QSpinBox()
        self._flow_default_zoom_spin.setRange(10, 9_999_999)
        self._flow_default_zoom_spin.setSuffix(" %")
        self._flow_default_zoom_spin.setToolTip(
            "相对「整图适配」视图：100% 与适配一致，50% 再缩小一半；"
            "可填任意更大百分比以放大（分析完成、播放路径、手动播放均用此比例）"
        )
        general_form.addRow("决策树可视化默认缩放:", self._flow_default_zoom_spin)

        self._flow_play_now_btn = QPushButton("播放决策树可视化")
        self._flow_play_now_btn.setToolTip(
            "使用当前已加载的决策路径重新播放动画（若尚未分析则无可播放内容）"
        )
        self._flow_play_now_btn.clicked.connect(self._on_play_decision_flow_now)
        general_form.addRow("", self._flow_play_now_btn)

        self._decision_flow_play_handler: Callable[[], None] | None = None

        form_layout.addWidget(general_group)

        # ── Notification group ────────────────────────────────────────────
        notification_group = QGroupBox("通知")
        notification_form = QFormLayout(notification_group)

        self._notify_enabled_check = QCheckBox("启用通知（总开关）")
        self._notify_enabled_check.setToolTip(
            "勾选后，满足下方对应场景开关且配置了渠道时，将决策消息推送到钉钉/微信。"
        )
        notification_form.addRow("启用:", self._notify_enabled_check)

        self._dingtalk_webhook_edit = QLineEdit()
        self._dingtalk_webhook_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._dingtalk_webhook_edit.setPlaceholderText(
            "https://oapi.dingtalk.com/robot/send?access_token=..."
        )
        ding_row = QHBoxLayout()
        ding_row.addWidget(self._dingtalk_webhook_edit)
        self._show_ding_btn = QPushButton("显示")
        self._show_ding_btn.setCheckable(True)
        self._show_ding_btn.setFixedWidth(52)
        self._show_ding_btn.toggled.connect(self._toggle_dingtalk_visibility)
        ding_row.addWidget(self._show_ding_btn)
        notification_form.addRow("钉钉 Webhook:", ding_row)

        self._dingtalk_secret_edit = QLineEdit()
        self._dingtalk_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._dingtalk_secret_edit.setPlaceholderText("可选：加签 Secret（SEC 开头）")
        self._dingtalk_secret_edit.setToolTip(
            "钉钉机器人若使用「加签」安全设置，填此 Secret；仅用关键词/IP 限制可留空。"
        )
        notification_form.addRow("钉钉加签 Secret:", self._dingtalk_secret_edit)

        self._wechat_webhook_edit = QLineEdit()
        self._wechat_webhook_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._wechat_webhook_edit.setPlaceholderText(
            "微信推送 URL（Bark / Server酱 / 企业微信群机器人）"
        )
        wechat_row = QHBoxLayout()
        wechat_row.addWidget(self._wechat_webhook_edit)
        self._show_wechat_btn = QPushButton("显示")
        self._show_wechat_btn.setCheckable(True)
        self._show_wechat_btn.setFixedWidth(52)
        self._show_wechat_btn.toggled.connect(self._toggle_wechat_visibility)
        wechat_row.addWidget(self._show_wechat_btn)
        notification_form.addRow("微信 Webhook:", wechat_row)

        self._notify_new_order_check = QCheckBox("产生新的下单决策（入场/止盈/止损）")
        notification_form.addRow("场景 · 新下单:", self._notify_new_order_check)

        self._notify_entry_filled_check = QCheckBox("计划单被触及、确认入场成交")
        notification_form.addRow("场景 · 入场成交:", self._notify_entry_filled_check)

        self._notify_exit_check = QCheckBox("持仓出场（止盈/止损/AI 平仓）")
        notification_form.addRow("场景 · 出场:", self._notify_exit_check)

        self._notify_manage_check = QCheckBox("持仓管理调整（移动止损/止盈）")
        notification_form.addRow("场景 · 持仓调整:", self._notify_manage_check)

        self._notify_no_trade_check = QCheckBox("观望/不下单结论也通知")
        notification_form.addRow("场景 · 观望:", self._notify_no_trade_check)

        self._notify_error_check = QCheckBox("分析失败/异常时通知")
        notification_form.addRow("场景 · 异常:", self._notify_error_check)

        self._notify_api_error_check = QCheckBox("API 调用异常时通知（网络/鉴权/限流等）")
        self._notify_api_error_check.setToolTip(
            "分析或追问时若 AI API 调用失败，将额外推送到已配置的钉钉/微信渠道。"
        )
        notification_form.addRow("场景 · API 异常:", self._notify_api_error_check)

        self._notify_timeout_spin = QSpinBox()
        self._notify_timeout_spin.setRange(1, 120)
        self._notify_timeout_spin.setSuffix(" s")
        notification_form.addRow("请求超时:", self._notify_timeout_spin)

        self._notify_test_btn = QPushButton("发送测试通知")
        self._notify_test_btn.setToolTip(
            "使用当前填写的渠道发送一条测试消息（无需先保存）。"
        )
        self._notify_test_btn.clicked.connect(self._on_send_test_notification)
        notification_form.addRow("", self._notify_test_btn)

        form_layout.addWidget(notification_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root_layout.addWidget(buttons)

    def _load_values(self) -> None:
        p = self._settings.provider
        g = self._settings.general

        self._model_edit.setText(p.model)
        self._base_url_edit.setText(p.base_url)
        self._api_key_edit.setText(p.api_key)
        self._thinking_check.setChecked(p.thinking)

        idx = self._reasoning_effort_combo.findText(p.reasoning_effort)
        if idx >= 0:
            self._reasoning_effort_combo.setCurrentIndex(idx)

        self._context_window_spin.setValue(p.context_window)
        self._analysis_bar_count_spin.setValue(g.analysis_bar_count)
        self._refresh_interval_spin.setValue(g.refresh_interval_ms)
        self._mt5_terminal_path_edit.setText(getattr(g, "mt5_terminal_path", "") or "")
        self._auto_resume_chart_check.setChecked(
            bool(getattr(g, "auto_resume_chart_after_analysis", False))
        )
        self._keep_analysis_check.setChecked(
            bool(getattr(g, "keep_analysis", False))
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
        self._keep_analysis_time_window_check.toggled.connect(
            self._sync_keep_analysis_time_widgets_enabled
        )
        self._keep_analysis_time_start_edit.timeChanged.connect(
            self._update_keep_analysis_time_hint
        )
        self._keep_analysis_time_end_edit.timeChanged.connect(
            self._update_keep_analysis_time_hint
        )
        self._update_keep_analysis_time_hint()
        self._context_warning_spin.setValue(int(g.context_warning_threshold_pct))
        self._stream_font_spin.setValue(int(getattr(g, "stream_pane_font_pt", 11)))
        self._chart_seq_font_spin.setValue(int(getattr(g, "chart_seq_label_font_pt", 7)))
        self._incremental_max_new_bars_spin.setValue(
            int(getattr(g, "incremental_max_new_bars", 10))
        )
        stance = getattr(g, "decision_stance", "conservative")
        stance_idx = self._decision_stance_combo.findData(stance)
        if stance_idx >= 0:
            self._decision_stance_combo.setCurrentIndex(stance_idx)
        self._last_symbol_edit.setText(g.last_symbol)
        self._last_timeframe_edit.setText(g.last_timeframe)
        self._flow_auto_play_check.setChecked(
            getattr(g, "decision_flow_auto_play", False)
        )
        self._flow_play_seconds_spin.setValue(
            getattr(g, "decision_flow_play_seconds", 50)
        )
        self._flow_default_zoom_spin.setValue(
            int(getattr(g, "decision_flow_default_zoom_pct", 500))
        )

        n = getattr(self._settings, "notification", None)
        if n is not None:
            self._notify_enabled_check.setChecked(bool(getattr(n, "enabled", False)))
            self._dingtalk_webhook_edit.setText(getattr(n, "dingtalk_webhook", "") or "")
            self._dingtalk_secret_edit.setText(getattr(n, "dingtalk_secret", "") or "")
            self._wechat_webhook_edit.setText(getattr(n, "wechat_webhook", "") or "")
            self._notify_new_order_check.setChecked(bool(getattr(n, "notify_new_order", True)))
            self._notify_entry_filled_check.setChecked(bool(getattr(n, "notify_entry_filled", True)))
            self._notify_exit_check.setChecked(bool(getattr(n, "notify_exit", True)))
            self._notify_manage_check.setChecked(bool(getattr(n, "notify_manage", True)))
            self._notify_no_trade_check.setChecked(bool(getattr(n, "notify_no_trade", False)))
            self._notify_error_check.setChecked(bool(getattr(n, "notify_error", False)))
            self._notify_api_error_check.setChecked(
                bool(getattr(n, "notify_api_error", False))
            )
            self._notify_timeout_spin.setValue(int(getattr(n, "request_timeout_s", 10)))

    @staticmethod
    def _validate_provider_fields(model: str, base_url: str) -> str | None:
        """Return user-facing error text, or None if fields look consistent."""
        if model.startswith(("http://", "https://")) and not base_url.startswith(
            ("http://", "https://")
        ):
            return (
                "「模型」与「Base URL」似乎填反了：\n"
                "• 模型应填模型名，如 deepseek-v4-pro 或 claude-sonnet-4-6\n"
                "• Base URL 应填接口地址，如 https://api.deepseek.com"
            )
        if base_url.startswith(("http://", "https://")):
            return None
        if not base_url:
            return "请填写 Base URL（API 接口地址）。"
        return (
            f"Base URL 不是有效网址（当前：{base_url}）。\n"
            "DeepSeek 示例：https://api.deepseek.com\n"
            "PackyAPI 示例：https://www.packyapi.com/v1\n"
            "Agnes 示例：https://apihub.agnes-ai.com/v1（模型 agnes-2.0-flash）"
        )

    def _on_save(self) -> None:
        p = self._settings.provider
        g = self._settings.general

        model = self._model_edit.text().strip()
        base_url = self._base_url_edit.text().strip()
        field_err = self._validate_provider_fields(model, base_url)
        if field_err:
            QMessageBox.warning(self, "AI 提供商配置有误", field_err)
            return

        p.model = model
        p.base_url = base_url
        p.api_key = self._api_key_edit.text()
        p.thinking = self._thinking_check.isChecked()
        p.reasoning_effort = self._reasoning_effort_combo.currentText()  # type: ignore[assignment]
        p.context_window = self._context_window_spin.value()

        g.analysis_bar_count = self._analysis_bar_count_spin.value()
        g.refresh_interval_ms = self._refresh_interval_spin.value()
        g.mt5_terminal_path = self._mt5_terminal_path_edit.text().strip()
        g.auto_resume_chart_after_analysis = self._auto_resume_chart_check.isChecked()
        g.keep_analysis = self._keep_analysis_check.isChecked()
        g.keep_analysis_time_window_enabled = (
            self._keep_analysis_time_window_check.isChecked()
        )
        g.keep_analysis_time_start = (
            self._keep_analysis_time_start_edit.time().toString("HH:mm")
        )
        g.keep_analysis_time_end = (
            self._keep_analysis_time_end_edit.time().toString("HH:mm")
        )
        g.keep_analysis_bypass_with_position = (
            self._keep_analysis_bypass_position_check.isChecked()
        )
        g.context_warning_threshold_pct = float(self._context_warning_spin.value())
        g.stream_pane_font_pt = self._stream_font_spin.value()
        g.chart_seq_label_font_pt = self._chart_seq_font_spin.value()
        g.incremental_max_new_bars = self._incremental_max_new_bars_spin.value()
        g.decision_stance = self._decision_stance_combo.currentData()  # type: ignore[assignment]
        g.last_symbol = self._last_symbol_edit.text().strip()
        g.last_timeframe = self._last_timeframe_edit.text().strip()
        g.decision_flow_auto_play = self._flow_auto_play_check.isChecked()
        g.decision_flow_play_seconds = self._flow_play_seconds_spin.value()
        g.decision_flow_default_zoom_pct = self._flow_default_zoom_spin.value()

        self._sync_notification_settings()

        save_settings(self._settings, SETTINGS_JSON_PATH)
        self.accept()

    def _sync_keep_analysis_time_widgets_enabled(self, *_args: object) -> None:
        enabled = self._keep_analysis_time_window_check.isChecked()
        self._keep_analysis_time_start_edit.setEnabled(enabled)
        self._keep_analysis_time_end_edit.setEnabled(enabled)
        self._keep_analysis_bypass_position_check.setEnabled(enabled)
        self._keep_analysis_time_hint_label.setEnabled(enabled)
        self._update_keep_analysis_time_hint()

    def _update_keep_analysis_time_hint(self, *_args: object) -> None:
        from pa_agent.config.tracking_schedule import (
            format_tracking_window_hint,
            is_overnight_window,
        )

        start = self._keep_analysis_time_start_edit.time().toString("HH:mm")
        end = self._keep_analysis_time_end_edit.time().toString("HH:mm")
        overnight = is_overnight_window(start, end)
        self._keep_analysis_time_sep_label.setText("至次日" if overnight else "至")
        data_source = self._data_source
        if data_source is None and self.parent() is not None:
            ctx = getattr(self.parent(), "_ctx", None)
            if ctx is not None:
                data_source = getattr(ctx, "data_source", None)
        self._keep_analysis_time_hint_label.setText(
            format_tracking_window_hint(start, end, data_source=data_source)
        )

    def _sync_notification_settings(self) -> None:
        """Write notification widgets back into self._settings.notification."""
        n = getattr(self._settings, "notification", None)
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

    def focus_api_key_field(self) -> None:
        """Focus the API Key field (e.g. when prompting on first launch)."""
        self._api_key_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self._api_key_edit.selectAll()

    def set_decision_flow_play_handler(self, handler: Callable[[], None] | None) -> None:
        """Register callback invoked when user clicks 播放决策树可视化."""
        self._decision_flow_play_handler = handler

    def _on_play_decision_flow_now(self) -> None:
        # Allow previewing playback without pressing “保存”:
        # sync relevant fields from widgets into the in-memory settings object.
        g = self._settings.general
        g.decision_flow_auto_play = self._flow_auto_play_check.isChecked()
        g.decision_flow_play_seconds = self._flow_play_seconds_spin.value()
        g.decision_flow_default_zoom_pct = self._flow_default_zoom_spin.value()

        if self._decision_flow_play_handler is not None:
            self._decision_flow_play_handler()

    def _open_api_key_help_url(self) -> None:
        QDesktopServices.openUrl(QUrl(_API_KEY_HELP_URL))

    def _open_agent_tutorial_url(self) -> None:
        QDesktopServices.openUrl(QUrl(_AGENT_TUTORIAL_URL))

    def _toggle_api_key_visibility(self, checked: bool) -> None:
        if checked:
            self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._show_key_btn.setText("隐藏")
        else:
            self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._show_key_btn.setText("显示")

    def _toggle_dingtalk_visibility(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self._dingtalk_webhook_edit.setEchoMode(mode)
        self._show_ding_btn.setText("隐藏" if checked else "显示")

    def _toggle_wechat_visibility(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self._wechat_webhook_edit.setEchoMode(mode)
        self._show_wechat_btn.setText("隐藏" if checked else "显示")

    def _provider_settings_from_form(self):
        from pa_agent.config.settings import AIProviderSettings

        return AIProviderSettings(
            model=self._model_edit.text().strip(),
            base_url=self._base_url_edit.text().strip(),
            api_key=self._api_key_edit.text().strip(),
            thinking=self._thinking_check.isChecked(),
            reasoning_effort=self._reasoning_effort_combo.currentText(),  # type: ignore[arg-type]
            context_window=self._context_window_spin.value(),
        )

    def _on_check_api_health(self) -> None:
        provider = self._provider_settings_from_form()
        if not provider.api_key:
            QMessageBox.warning(self, "API 检测", "请先填写 API Key。")
            return
        if not provider.base_url:
            QMessageBox.warning(self, "API 检测", "请先填写 Base URL。")
            return
        if not provider.model:
            QMessageBox.warning(self, "API 检测", "请先填写模型 ID。")
            return

        self._api_health_btn.setEnabled(False)
        self._api_health_btn.setText("检测中…")
        try:
            from pa_agent.ai.api_health import check_api_health

            result = check_api_health(provider)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "API 检测", f"检测失败：{exc}")
            return
        finally:
            self._api_health_btn.setEnabled(True)
            self._api_health_btn.setText("检测 API 连通性")

        if result.ok:
            detail = (
                f"延迟约 {result.latency_ms:.0f} ms\n"
                f"思考字符: {result.reasoning_chars}\n"
                f"回答字符: {result.content_chars}"
            )
            QMessageBox.information(self, "API 检测", f"API 调用成功。\n\n{detail}")
            return

        QMessageBox.warning(self, "API 检测", f"API 调用失败：\n\n{result.message}")

    def _on_send_test_notification(self) -> None:
        """Send a test message using the currently-entered channel fields."""
        self._sync_notification_settings()
        n = getattr(self._settings, "notification", None)
        if n is None:
            return
        if not (n.dingtalk_webhook or n.wechat_webhook):
            QMessageBox.warning(
                self, "通知", "请先填写至少一个渠道（钉钉或微信 Webhook）。"
            )
            return

        from pa_agent.notification.channels import DingTalkChannel, WeChatChannel
        from pa_agent.notification.events import NotificationEvent, NotificationMessage

        message = NotificationMessage(
            event=NotificationEvent.NEW_ORDER,
            title="🔔 Trading Agent 测试通知",
            text="这是一条来自 Trading Agent 的测试消息。\n若你收到它，说明通知渠道配置正确。",
        )
        timeout = int(n.request_timeout_s or 10)
        errors: list[str] = []
        sent = 0
        if n.dingtalk_webhook:
            res = DingTalkChannel(
                webhook=n.dingtalk_webhook, secret=n.dingtalk_secret, timeout_s=timeout
            ).send(message)
            if res.ok:
                sent += 1
            else:
                errors.append(f"钉钉: {res.error or res.status}")
        if n.wechat_webhook:
            res = WeChatChannel(webhook=n.wechat_webhook, timeout_s=timeout).send(message)
            if res.ok:
                sent += 1
            else:
                errors.append(f"微信: {res.error or res.status}")

        if errors:
            QMessageBox.warning(
                self,
                "通知测试",
                f"成功 {sent} 个渠道；失败：\n" + "\n".join(errors),
            )
        else:
            QMessageBox.information(self, "通知测试", f"测试通知已发送（{sent} 个渠道）。")
