# Trading Agent 开发与上游合并操作手册

> **文档性质**：可执行 SOP（标准操作流程）  
> **适用读者**：维护 Trading Agent 的开发者、Cursor / Codex 等 AI Agent  
> **仓库路径**：`E:\Dev\Trading\PA_Agent`  
> **生产分支**：`trading-agent`  
> **上游只读**：`upstream/main` → `rosemarycox5334-debug/PA_Agent`

---

## Agent 必读摘要（AI 按此执行）

若你是 Agent，接到与「合并上游」「同步 upstream」「减少冲突」「Trading Agent 定制」相关的任务，**必须先读本节**，再读后文细节。

### 身份与边界

| 项 | 规则 |
|----|------|
| **你的主线** | 只在 `trading-agent` 分支（或其 `feat/*` 子分支）上改代码 |
| **不要改** | `upstream/main` 上的提交；不要在 `main` 上堆定制 |
| **定制代码位置** | 优先 `pa_agent/trading_agent/`、`licensing/`、`notification/`、`positions/` |
| **提示词** | `prompt_engineering/**` **永远跟上游**（B 类），不要擅自改 |
| **禁止** | 整文件用 backup 覆盖 `main_window.py` / `two_stage.py`；不要删除 `enrich_app_context` 接线 |

### 任务路由

| 用户意图 | Agent 应做 |
|----------|------------|
| 日常修 bug / 新功能 | `git checkout trading-agent` → 改代码 → 测试 → commit（用户要求时再 push） |
| 上游有更新，要合进来 | 执行 [§4 合并上游 SOP](#4-合并上游-sop) |
| 解决 merge 冲突 | 执行 [§5 冲突处理手册](#5-冲突处理手册) |
| 新增 Trading Agent 专属能力 | 执行 [§6 新增定制功能放哪里](#6-新增定制功能放哪里) |
| 用户要在 main 上开发 | **劝阻**，引导到 `trading-agent` |

### 合并上游 Agent 检查清单（逐步执行）

```
[ ] 1. 确认当前分支：git branch --show-current  → 应为 trading-agent
[ ] 2. 工作区干净：git status  → 无未提交改动（有则先 commit 或 stash）
[ ] 3. git fetch upstream
[ ] 4. git merge upstream/main -m "merge upstream/main YYYY-MM-DD"
[ ] 5. 若冲突：
        - A 类路径 → 保留我方（通常 .gitattributes 已自动处理）
        - B 类 prompt_engineering/** → 保留上游
        - C 类 → 按 §5 逐文件人工合并，禁止整文件覆盖
[ ] 6. 确认接线仍在：
        - app_context.py 末尾 enrich_app_context(ctx)
        - main_window.py 中 ChartLiveController + wire_main_window/wire_after_sidebar
        - settings_dialog.py 中 _ta_settings
[ ] 7. python -m pytest tests/unit -q
[ ] 8. 用户要求时：git push origin trading-agent
[ ] 9. 全文搜索 <<<<<<< 确保无残留冲突标记
```

### 一键脚本（人类或 Agent 均可调用）

```powershell
cd E:\Dev\Trading\PA_Agent
.\scripts\merge-upstream.ps1
```

---

## 1. 机制说明：为什么要这样

Trading Agent 是在开源 **PA_Agent** 之上的**定制发行版**，两边会长期并行演进：

- **上游**：新数据源、AI 校验、GUI 大改、提示词优化……
- **你方**：授权、打包、通知、持仓、图表实时更新开关、品牌……

若所有定制都写进 `main_window.py`、`app_context.py`，每次上游更新都会产生大量冲突。

**解法**：

1. **分支隔离**：`trading-agent` = 你的唯一生产主线；`upstream/main` 只用来 `merge`，不在上面开发。
2. **代码分层**：定制进 `pa_agent/trading_agent/` 等独立包；核心文件只留「接线」。
3. **合并策略**：`.gitattributes` 对 A/B 类路径自动选边；C 类少数文件人工合并。

```
upstream/main  ──fetch/merge──►  trading-agent  ──push──►  origin (你的 fork)
     ▲                                │
     │                                ├── pa_agent/trading_agent/  （定制层）
     │                                ├── licensing/ notification/ positions/
     └── 只读，不 commit              └── main_window 等（上游 + 少量接线）
```

---

## 2. 首次环境配置（每个 clone 做一次）

```powershell
cd E:\Dev\Trading\PA_Agent

# 确认远程
git remote -v
# origin   → 你的 fork（liao7877/PA_Agent）
# upstream → rosemarycox5334-debug/PA_Agent

# 切到生产分支
git checkout trading-agent

# 配置 merge 驱动（A/B 类自动选边）
.\scripts\setup-merge-drivers.ps1

# 建议：记住冲突解法，减少重复劳动
git config --local rerere.enabled true
```

验证：

```powershell
git branch --show-current          # trading-agent
git config --local --get merge.ours.driver   # true
python -c "from pa_agent.trading_agent.entry import main; print('ok')"
```

---

## 3. 日常开发流程

### 3.1 标准流程

```powershell
git checkout trading-agent
git pull origin trading-agent          # 多人协作时

# 开发…
python run.py                          # 本地验证
python -m pytest tests/unit -q         # 单测

git add <files>
git commit -m "feat: 描述"
git push origin trading-agent          # 需要同步到 fork 时
```

### 3.2 较大的新功能

```powershell
git checkout trading-agent
git checkout -b feat/你的功能名

# 开发…测试…
git checkout trading-agent
git merge feat/你的功能名
git branch -d feat/你的功能名
```

### 3.3 不要在哪些分支上做什么

| 分支 | 用途 | 禁止 |
|------|------|------|
| `trading-agent` | 日常开发与发布 | — |
| `upstream/main` | 只读参照 | ❌ 不要 commit |
| `main` | 可保留为上游快照 | ❌ 不要堆定制 |
| `main_backup` | 历史归档 | ❌ 不要再维护 |

---

## 4. 合并上游 SOP

**何时做**：上游 `rosemarycox5334-debug/PA_Agent` 有明显更新（新功能、重要 bugfix）时；建议每隔 1–2 周或发版前做一次。

### 4.1 推荐：脚本合并

```powershell
cd E:\Dev\Trading\PA_Agent
.\scripts\merge-upstream.ps1
```

脚本会：`fetch upstream` → `merge upstream/main` → 跑 `pytest tests/unit` →（默认）`push origin`。

仅合并不推送、不测试：

```powershell
.\scripts\merge-upstream.ps1 -NoPush -NoTest
```

### 4.2 手动合并（与脚本等价）

```powershell
cd E:\Dev\Trading\PA_Agent
git checkout trading-agent
git status                            # 必须干净
git fetch upstream
git merge upstream/main -m "merge upstream/main $(Get-Date -Format yyyy-MM-dd)"
```

无冲突则：

```powershell
python -m pytest tests/unit -q
git push origin trading-agent
```

有冲突 → [§5](#5-冲突处理手册)。

### 4.3 合并后冒烟检查（人类或 Agent）

| 步骤 | 操作 | 预期 |
|------|------|------|
| 1 | `python run.py` | 窗口标题为 Trading Agent；源码模式跳过许可 |
| 2 | 设置 → 通知 / MT5 路径 | 定制设置页正常 |
| 3 | 图表「实时更新」开关 | 可勾选、可冻结 |
| 4 | 提交分析（有 API 时） | 流程正常；失败时有可读错误 |
| 5 | `rg '<<<<<<<' .` | 无冲突残留 |

---

## 5. 冲突处理手册

### 5.1 三类文件（A / B / C）

合并时 Git 按 `.gitattributes` 与路径分类处理：

#### A 类 — 保留 Trading Agent（`merge=ours`）

冲突时**保留我方**。完整列表见 `pa_agent/trading_agent/manifest.py` → `MERGE_OURS_GLOBS`。

主要包括：

- `pa_agent/trading_agent/**`
- `pa_agent/licensing/**`、`notification/**`、`positions/**`
- `build.bat`、`Trading_Agent.spec`、打包脚本与授权工具
- `docs/打包与授权.md`、`docs/本操作手册.md` 等交付文档

**Agent 规则**：A 类若仍出现冲突标记，选 **ours** / 保留 `trading-agent` 侧内容，不要换成上游。

#### B 类 — 保留上游（`merge=theirs`）

- `prompt_engineering/**` — 提示词**以上游为准**

**Agent 规则**：不要「帮用户改提示词」除非用户明确要求；合并时选 **theirs**。

#### C 类 — 必须人工合并（看 diff 接逻辑）

| 文件 | 合并原则 |
|------|----------|
| `pa_agent/gui/main_window.py` | 接上游 GUI/分析流程改动；**保留** `ChartLiveController`、`wire_main_window`、`wire_after_sidebar` 及对 `trading_agent` 的薄包装调用 |
| `pa_agent/orchestrator/two_stage.py` | 接上游校验/重试/编排；**保留** Stage2 `decision_preserved`、thinking 空内容回退等已合入逻辑 |
| `pa_agent/ai/deepseek_client.py` | 接上游 Provider；**保留** GPT-5/Agnes 等已适配代码 |
| `pa_agent/config/settings.py` | 接上游新字段；Trading Agent 字段由 `settings_ui` 读写，不删 notification 等模型 |
| `pa_agent/ai/json_validator.py` | 接上游校验增强；谨慎合并 |
| `pa_agent/app_context.py` | 接上游 bootstrap 改动；**末尾必须保留** `return enrich_app_context(ctx)` |
| `pa_agent/gui/settings_dialog.py` | 接上游设置项；**保留** `_ta_settings.install_*` / `load` / `save` |
| `pa_agent/data/factory.py`、`mt5.py` | 接新数据源；保留 `mt5_terminal_path` 传参 |

### 5.2 C 类「必须保留」的接线代码

**`app_context.py` 末尾：**

```python
from pa_agent.trading_agent.bootstrap import enrich_app_context
return enrich_app_context(ctx)
```

**`main_window.py`（示意位置）：**

```python
from pa_agent.trading_agent.chart_live import ChartLiveController
# __init__ 内、_setup_ui 之前：
self._chart_live = ChartLiveController(self)
# __init__ 末尾：
from pa_agent.trading_agent.window_hooks import wire_main_window, wire_after_sidebar
wire_main_window(self, license_validator)
wire_after_sidebar(self)
```

**`settings_dialog.py`：**

```python
from pa_agent.trading_agent.settings_ui import TradingAgentSettingsExtension
self._ta_settings = TradingAgentSettingsExtension(self)
# _setup_ui 内：
self._ta_settings.install_general_fields(general_form)
self._ta_settings.install_notification_group(form_layout)
# _load_values / _on_save：
self._ta_settings.load(self._settings)
self._ta_settings.save(self._settings)
```

**`main.py`：**

```python
from pa_agent.trading_agent.entry import main
```

### 5.3 Agent 处理冲突的步骤

1. `git status` 列出 `both modified` 文件。
2. 对每个文件判断 A/B/C（查 `manifest.py` 或本文 §5.1）。
3. A → 保留 ours；B → 保留 theirs。
4. C → `git diff` 看双方改动意图：**接上游新逻辑 + 保留我方接线/定制行为**。
5. 删光 `<<<<<<<` / `=======` / `>>>>>>>`。
6. `git add` 已解决文件 → `git commit`（完成 merge commit）。
7. 跑测试与 §4.3 冒烟项。

### 5.4 常见错误（禁止）

| 错误做法 | 后果 |
|----------|------|
| 用 `main_backup` 整文件覆盖 C 类 | 丢失上游新功能 |
| 删除 `trading_agent` 包，把逻辑塞回 main_window | 下次合并更痛 |
| 合并时保留旧版 `prompt_engineering` | 与上游策略/Schema 脱节 |
| 在 `main` 上开发后 cherry-pick 一堆 | 重复劳动、易漏项 |
| 冲突未清完就 commit | 语法错误、运行时崩溃 |

---

## 6. 新增定制功能放哪里

**原则**：新定制尽量不进 C 类大文件；先进独立包，再在核心文件**加一行接线**。

| 你要加什么 | 放哪里 | 接线点 |
|------------|--------|--------|
| 新通知渠道 | `pa_agent/notification/` | `service.py`；设置 UI 进 `trading_agent/settings_ui.py` |
| 新授权规则 | `pa_agent/licensing/` | `guard.py` / `enforce.py`；菜单进 `licensing_ui.py` |
| 持仓相关逻辑 | `pa_agent/positions/` | `record_handlers.py` 或 `tracker.py` |
| 图表/分析后行为 | `pa_agent/trading_agent/chart_live.py` 或 `record_handlers.py` | `main_window` 薄方法委托 |
| 启动/品牌/许可 | `pa_agent/trading_agent/entry.py` | `main.py` 已委托，一般不用改 |
| 全局服务注册 | `pa_agent/trading_agent/bootstrap.py` | `app_context.py` 仅保留 enrich 调用 |
| 设置页新字段（Trading Agent 专属） | `trading_agent/settings_ui.py` + `config/settings.py` | `settings_dialog` 调 `_ta_settings` |

新增 A 类路径时，同步更新：

1. `pa_agent/trading_agent/manifest.py` → `MERGE_OURS_GLOBS`
2. `.gitattributes` 增加 `merge=ours` 规则
3. 本文 §5.1 表格（可选）

---

## 7. 定制集成层模块速查

| 文件 | 职责 |
|------|------|
| `trading_agent/entry.py` | 应用入口：许可校验 → bootstrap → MainWindow |
| `trading_agent/bootstrap.py` | `enrich_app_context()`：Notification + PositionTracker |
| `trading_agent/window_hooks.py` | 窗口标题、许可、侧栏 notifier 绑定 |
| `trading_agent/chart_live.py` | 图表实时更新开关与冻结语义 |
| `trading_agent/record_handlers.py` | 分析完成通知、持仓 tick、API 失败推送 |
| `trading_agent/licensing_ui.py` | 关于菜单、LicenseGuard、提交前门禁 |
| `trading_agent/settings_ui.py` | 通知 / MT5 路径 / 跟踪时段设置 UI |
| `trading_agent/manifest.py` | A/B/C 路径清单（与 `.gitattributes` 一致） |

---

## 8. 命令速查

```powershell
# 分支与远程
git branch -a
git remote -v
git checkout trading-agent

# 合并上游
git fetch upstream
git merge upstream/main
.\scripts\merge-upstream.ps1

# 测试与运行
python run.py
python -m pytest tests/unit -q

# 查冲突残留
rg "<<<<<<<" pa_agent

# 看某文件双方差异（合并中）
git diff --name-only --diff-filter=U
```

---

## 9. 相关文档

| 文档 | 内容 |
|------|------|
| `docs/上游合并策略.md` | 策略摘要（本文的精简版） |
| `docs/项目交接文档.md` | 模块总览与业务背景 |
| `docs/详细规格说明书.md` | 功能规格 SRS |
| `pa_agent/trading_agent/manifest.py` | A/B/C 路径机器可读清单 |
| `scripts/merge-upstream.ps1` | 合并自动化脚本 |
| `scripts/setup-merge-drivers.ps1` | 首次 merge driver 配置 |

---

## 10. 给 Agent 的提交信息约定

合并上游完成后，commit message 建议：

```
merge upstream/main YYYY-MM-DD
```

若合并后修了 C 类冲突，可追加：

```
merge upstream/main YYYY-MM-DD

- Resolve C-class conflicts in main_window, two_stage
- Preserve trading_agent wiring and decision_preserved
```

---

*文档版本：2026-06-15 · 与 `trading-agent` 分支配套维护*
