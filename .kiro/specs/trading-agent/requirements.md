# 需求文档：Trading Agent 核心特性

> EARS 风格需求摘要。完整 SRS 见 `docs/详细规格说明书.md`。  
> 版本：2026-06-15

---

## 1. 引言

Trading Agent 是 Windows 桌面 **价格行为 AI 辅助决策工具**。用户选定品种与周期后查看实时 K 线，手动触发两阶段 LLM 分析，获得结构化 JSON 决策与图表 overlay。**不执行任何交易动作**。

---

## 2. 需求列表

### R1：实时 K 线获取与图表绘制

**User Story:** 作为交易者，我想要在选定品种与周期下看到可刷新的 K 线图，且每根 bar 带序号，以便对照 AI 输出中的 K 引用。

#### Acceptance Criteria

1. WHEN 程序启动并完成数据源订阅， THE System SHALL 通过当前 `DataSource` 拉取 K 线并渲染 `ChartWidget`。
2. WHILE 数据源已连接且图表刷新未暂停， THE System SHALL 按 `general.refresh_interval_ms`（默认 1000ms）刷新最新快照。
3. WHEN 图表实时更新开启, THE System SHALL 在最右侧绘制 forming bar（空心样式，`closed=False`）。
4. THE ChartWidget SHALL 对已收盘 bar 渲染序号标签（K1 为最新已收盘）。
5. IF 数据源连续失败, THEN THE System SHALL 在状态栏提示延迟，且不抛出未捕获异常。

---

### R2：图表实时更新开关

**User Story:** 作为交易者，我想要用开关控制图表是否实时刷新，以便在「盯盘」与「对照分析快照」之间切换。

#### Acceptance Criteria

1. THE System SHALL 在控制栏提供可勾选按钮「图表实时更新」，默认 **checked（开启）**。
2. WHEN 用户关闭该开关, THEN THE System SHALL 暂停 `RefreshLoop` 并将图表切换为 **纯已收盘** 帧。
3. WHEN 用户开启该开关, THEN THE System SHALL 恢复 `RefreshLoop` 并立即执行一次 `refresh_chart_once`。
4. WHEN 用户提交分析且开关为 **关闭**, THEN THE System SHALL 冻结图表为分析帧（仅已收盘，与 AI 表一致）。
5. WHEN 用户提交分析且开关为 **开启**, THEN THE System SHALL **不**因分析开始而强制冻结图表；forming bar 可继续显示。
6. WHEN 用户发送追问且开关为关闭, THEN THE System SHALL 刷新并冻结图表；导出 K 线表仍仅含已收盘 bar。
7. WHEN 分析完成且 `general.auto_resume_chart_after_analysis` 为 true, THEN THE System SHALL 自动恢复图表实时更新。
8. WHEN 持续跟踪（keep_analysis）开启且分析结束, THEN THE System SHALL 恢复图表实时更新以便检测下一根收盘。

---

### R3：两阶段 AI 分析

**User Story:** 作为交易者，我想要手动触发诊断与决策两阶段分析，并获得可复核的 JSON 与落盘记录。

#### Acceptance Criteria

1. WHEN 用户点击「提交分析」, THE System SHALL 构建 `build_analysis_frame`（仅已收盘 N 根）并启动 `TwoStageOrchestrator`。
2. THE System SHALL 在 Preflight 不满足时拒绝调用 AI 并显示可读错误（`format_preflight_failure`）。
3. WHEN Stage1 `gate_result ∈ {wait, unknown}`, THE System SHALL 跳过 Stage2 API 并生成不下单决策。
4. WHEN Stage2 完成, THE System SHALL 校验、归一化 JSON 并经由 `PendingWriter` 落盘。
5. THE System SHALL 在侧栏流式显示 reasoning 与 content token（若 Provider 支持）。

---

### R4：可插拔数据源

#### Acceptance Criteria

1. THE System SHALL 提供 `DataSource` 抽象，GUI 与编排层仅通过抽象访问数据。
2. THE System SHALL 支持至少：MT5、TradingView、AkShare、yfinance。
3. WHEN 用户切换数据源或品种/周期, THE System SHALL 取消进行中的 worker 并重新订阅。

---

### R5：通知

#### Acceptance Criteria

1. WHERE 用户配置钉钉或 Bark, THE System SHALL 在分析完成时推送决策摘要卡片。
2. WHEN API 调用失败, THE System SHALL 可选推送 `notify_api_failure` 消息。

---

### R6：授权（打包版）

#### Acceptance Criteria

1. WHEN 以打包可执行文件运行, THE System SHALL 在启动时校验 Ed25519 许可签名。
2. WHEN 以源码方式运行, THE System SHALL 跳过许可校验（开发模式）。
3. IF 许可无效或过期, THEN THE System SHALL 显示激活对话框或退出。

---

## 3. 追溯矩阵（摘要）

| 需求 | 主要实现 |
|------|----------|
| R1 | `data/refresh_loop.py`, `gui/chart_widget.py` |
| R2 | `gui/main_window.py` → `_on_chart_live_toggle` |
| R3 | `orchestrator/two_stage.py`, `ai/json_validator.py` |
| R4 | `data/factory.py`, `data/base.py` |
| R5 | `notification/service.py` |
| R6 | `licensing/validator.py`, `main.py` |

---

*变更时请同步更新 `docs/详细规格说明书.md` 中 FR-05 条目。*
