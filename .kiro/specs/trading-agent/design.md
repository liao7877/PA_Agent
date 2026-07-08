# 设计文档：Trading Agent 核心架构

> 关联：`requirements.md`、`docs/项目交接文档.md`  
> 版本：2026-06-15

---

## 1. 架构概览

```text
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  MainWindow │────▶│ AppContext   │────▶│ DataSource      │
│  (PyQt6)    │     │ (bootstrap)  │     │ MT5/TV/AkShare  │
└──────┬──────┘     └──────┬───────┘     └────────┬────────┘
       │                   │                       │
       │            ┌──────▼───────┐               │
       │            │ TwoStage     │◀──────────────┘
       │            │ Orchestrator │   analysis frame
       │            └──────┬───────┘
       │                   │
       ▼                   ▼
 ChartWidget          DeepSeekClient
 (live / frozen)      JsonValidator → PendingWriter
```

---

## 2. 图表帧双模式

| 模式 | 构建函数 | forming bar | 触发条件 |
|------|----------|-------------|----------|
| Live | `build_live_frame` | 可选包含 | `_chart_live_updates_enabled()` |
| Analysis | `build_analysis_frame` | 永不包含 | 提交分析、追问导出 |

### 2.1 刷新暂停语义

- `_chart_refresh_paused: bool` — RefreshLoop 是否向 ChartWidget 推送新帧
- `_chart_live_updates_enabled()` ≡ `not _chart_refresh_paused`
- UI 按钮 `_resume_chart_btn` 与 paused 状态反向同步（`blockSignals` 防递归）

### 2.2 分析开始时的分支

```python
live_on = self._chart_live_updates_enabled()
if not live_on:
    chart.set_frame_now(analysis_frame)
    self._set_chart_refresh_paused(True)
# live_on 时：不修改当前显示帧，RefreshLoop 继续
```

AI 输入 **始终** 使用 `analysis_frame`（纯已收盘），与图表显示模式解耦。

---

## 3. 两阶段编排

1. PreflightDataGate（本地，无 API）
2. Stage1 stream → validate → normalize → route
3. 若 gate 允许 → Stage2 stream → validate → normalize
4. `validation_retry` 按设置重试
5. 空内容 / JSON 截断 → fallback 策略（`two_stage.py`）

Worker 运行于 `QThread`；通过 Qt signal 更新 UI。

---

## 4. 组件装配（AppContext）

启动顺序：`main.py` → LicenseValidator → `AppContext.bootstrap()`：

| 字段 | 类型/模块 |
|------|-----------|
| settings | `config/settings.py` |
| data_source | `data/factory.py` |
| client | `ai/deepseek_client.py` |
| assembler | `ai/prompt_assembler.py` |
| validator | `ai/json_validator.py` |
| pending_writer | `records/pending_writer.py` |
| notifier | `notification/service.py` |
| position_tracker | `positions/tracker.py` |

---

## 5. 授权分层

| 层 | 职责 |
|----|------|
| `validator.py` | 签名校验、过期判断、开发 bypass |
| `activation_dialog.py` | 首次激活 UI |
| `guard.py` | 运行时功能门禁 |
| `enforce.py` | 打包环境检测 |

---

## 6. 配置持久化

- 路径：`config/settings.json`（用户本地，不入库）
- 模型：`pa_agent/config/settings.py`（Pydantic）
- API Key：Windows DPAPI 加密字段

---

## 7. 测试策略

| 层级 | 目录 | 重点 |
|------|------|------|
| Unit | `tests/unit/` | 校验器、归一化、设置往返、通知 |
| Integration | `tests/integration/` | 两阶段异常路径 |
| Property | `tests/property/` | 路由器确定性、不下单 invariant |

---

## 8. 与 backup 分支差异说明（2026-06-15）

| 项 | main_backup | 当前 main + 工作区 |
|----|-------------|-------------------|
| 图表实时更新 | 可切换开关 | **已对齐** |
| 品牌 | Trading Agent | Trading Agent |
| 上游能力 | — | East Money 路由、QClaw/WorkBuddy、validation_retry 等保留 |
| 提示词 | 定制版 | **以上游为准** |

---

*详细文件职责见 `docs/文件索引.md`。*
