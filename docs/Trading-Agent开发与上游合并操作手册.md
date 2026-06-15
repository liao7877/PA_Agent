# Trading Agent 开发与上游合并操作手册

> **文档性质**：可执行 SOP（标准操作流程）  
> **适用读者**：维护 Trading Agent 的开发者、Cursor / Codex 等 AI Agent  
> **仓库路径**：`E:\Dev\Trading\PA_Agent`  
> **生产分支**：`main`（Trading Agent 定制版，日常开发在此）  
> **上游只读**：`upstream/main` → `rosemarycox5334-debug/PA_Agent`  
> **归档分支**：`archive/upstream-main`（合并定制前的纯上游快照，只读参照）

---

## Agent 必读摘要（AI 按此执行）

若你是 Agent，接到与「合并上游」「同步 upstream」「减少冲突」「Trading Agent 定制」相关的任务，**必须先读本节**，再读后文细节。

### 身份与边界

| 项 | 规则 |
|----|------|
| **你的主线** | 在 **`main`** 分支（或其 `feat/*` 子分支）上改代码 |
| **不要改** | 远程 `upstream/main`（勿 push）；不要向 `archive/*` 提交 |
| **定制代码位置** | 优先 `pa_agent/trading_agent/`、`licensing/`、`notification/`、`positions/` |
| **提示词** | `prompt_engineering/**` **永远跟上游**（B 类），不要擅自改 |
| **禁止** | 整文件用 backup 覆盖 `main_window.py` / `two_stage.py`；不要删除 `enrich_app_context` 接线 |

### 任务路由

| 用户意图 | Agent 应做 |
|----------|------------|
| 日常修 bug / 新功能 | 确认在 `main` → 改代码 → 测试 → commit（用户要求时再 push） |
| 上游有更新，要合进来 | 执行 [§4 合并上游 SOP](#4-合并上游-sop) |
| 解决 merge 冲突 | 执行 [§5 冲突处理手册](#5-冲突处理手册) |
| 新增 Trading Agent 专属能力 | 执行 [§6 新增定制功能放哪里](#6-新增定制功能放哪里) |
| 用户要在 `upstream/main` 上开发 | **劝阻**；定制只在 `main`，上游仅用于 merge |

### 合并上游 Agent 检查清单（逐步执行）

```
[ ] 1. 确认当前分支：git branch --show-current  → 应为 main
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
[ ] 8. 用户要求时：git push origin main
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

**分支角色**（2026-06 起）：

| 分支 | 角色 |
|------|------|
| **`main`** | 你的生产主线（Trading Agent），**日常开发默认在此** |
| **`upstream/main`** | 上游仓库只读快照，仅 `fetch` + `merge` 进 `main` |
| **`archive/upstream-main`** | 引入定制前的纯上游 `main` 归档，仅供对照，不开发 |
| **`main_backup`** | 更早的定制尝试归档，不再维护 |

**解法**：

1. **在 `main` 上开发**，定期把 `upstream/main` merge 进来。
2. **代码分层**：定制进 `pa_agent/trading_agent/` 等独立包；核心文件只留「接线」。
3. **合并策略**：`.gitattributes` 对 A/B 类路径自动选边；C 类少数文件人工合并。

```
upstream/main  ──fetch/merge──►  main  ──push──►  origin/main (你的 fork)
     ▲                              │
     │                              ├── pa_agent/trading_agent/  （定制层）
     │                              ├── licensing/ notification/ positions/
     └── 只读，不 push              └── main_window 等（上游 + 少量接线）
```

---

## 2. 首次环境配置（每个 clone 做一次）

```powershell
cd E:\Dev\Trading\PA_Agent

# 确认远程
git remote -v
# origin   → 你的 fork（liao7877/PA_Agent）
# upstream → rosemarycox5334-debug/PA_Agent

# 切到生产分支（通常 clone 后默认即为 main）
git checkout main

# 配置 merge 驱动（A/B 类自动选边）
.\scripts\setup-merge-drivers.ps1

# 建议：记住冲突解法，减少重复劳动
git config --local rerere.enabled true
```

验证：

```powershell
git branch --show-current          # main
git config --local --get merge.ours.driver   # true
python -c "from pa_agent.trading_agent.entry import main; print('ok')"
```

---

## 3. 日常开发流程

### 3.1 标准流程

```powershell
git checkout main
git pull origin main                 # 多人协作时

# 开发…
python run.py                          # 本地验证
python -m pytest tests/unit -q         # 单测

git add <files>
git commit -m "feat: 描述"
git push origin main                   # 需要同步到 fork 时
```

### 3.2 较大的新功能

```powershell
git checkout main
git checkout -b feat/你的功能名

# 开发…测试…
git checkout main
git merge feat/你的功能名
git branch -d feat/你的功能名
```

### 3.3 分支用途一览

| 分支 | 用途 | 禁止 |
|------|------|------|
| **`main`** | 日常开发与发布（Trading Agent） | — |
| `upstream/main` | 上游只读参照（`git fetch upstream`） | ❌ 不要 commit / push |
| `archive/upstream-main` | 旧版纯上游快照归档 | ❌ 不要开发 |
| `main_backup` | 历史定制归档 | ❌ 不要再维护 |

> **说明**：早期曾用 `trading-agent` 作为生产分支名，已合并重命名为 **`main`**。若文档或脚本仍出现 `trading-agent`，一律视为 `main`。

---

## 4. 合并上游 SOP

**何时做**：上游 `rosemarycox5334-debug/PA_Agent` 有明显更新时；建议每隔 1–2 周或发版前做一次。

### 4.1 推荐：脚本合并

```powershell
cd E:\Dev\Trading\PA_Agent
.\scripts\merge-upstream.ps1
```

脚本会：`fetch upstream` → `merge upstream/main` → 跑 `pytest tests/unit` →（默认）`push origin main`。

仅合并不推送、不测试：

```powershell
.\scripts\merge-upstream.ps1 -NoPush -NoTest
```

### 4.2 手动合并（与脚本等价）

```powershell
cd E:\Dev\Trading\PA_Agent
git checkout main
git status                            # 必须干净
git fetch upstream
git merge upstream/main -m "merge upstream/main $(Get-Date -Format yyyy-MM-dd)"
```

无冲突则：

```powershell
python -m pytest tests/unit -q
git push origin main
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

### 4.4 首次把新 `main` 推到 fork（换分支结构后）

若远程 `origin/main` 仍是旧纯上游，需用定制版覆盖（**确认无他人依赖旧历史后再做**）：

```powershell
git push origin main --force-with-lease
git push origin archive/upstream-main
```

---

## 5. 冲突处理手册

### 5.1 三类文件（A / B / C）

#### A 类 — 保留 Trading Agent（`merge=ours`）

冲突时**保留我方**（即当前 **`main`** 侧）。完整列表见 `pa_agent/trading_agent/manifest.py` → `MERGE_OURS_GLOBS`。

**Agent 规则**：A 类若仍出现冲突标记，选 **ours**，不要换成上游。

#### B 类 — 保留上游（`merge=theirs`）

- `prompt_engineering/**` — 提示词**以上游为准**

#### C 类 — 必须人工合并（看 diff 接逻辑）

| 文件 | 合并原则 |
|------|----------|
| `pa_agent/gui/main_window.py` | 接上游改动；**保留** `ChartLiveController`、`wire_main_window`、`wire_after_sidebar` |
| `pa_agent/orchestrator/two_stage.py` | 接上游编排；**保留** `decision_preserved`、thinking 回退等 |
| `pa_agent/ai/deepseek_client.py` | 接新 Provider；**保留** GPT-5/Agnes 适配 |
| `pa_agent/config/settings.py` | 接上游字段；Trading Agent 字段由 `settings_ui` 扩展 |
| `pa_agent/app_context.py` | **末尾保留** `return enrich_app_context(ctx)` |
| `pa_agent/gui/settings_dialog.py` | **保留** `_ta_settings` 扩展 |
| `pa_agent/data/factory.py`、`mt5.py` | 接新数据源；保留 `mt5_terminal_path` |

### 5.2 C 类「必须保留」的接线代码

（与先前相同，见 `app_context.py` / `main_window.py` / `settings_dialog.py` / `main.py` 中的 `trading_agent` 引用。）

### 5.3 Agent 处理冲突的步骤

1. `git status` → 列出冲突文件  
2. 判 A/B/C → 按 §5.1 选边  
3. C 类：**接上游新逻辑 + 保留我方接线**  
4. 清除冲突标记 → `git add` → 完成 merge commit  
5. 测试 + §4.3 冒烟  

### 5.4 常见错误（禁止）

| 错误做法 | 后果 |
|----------|------|
| 用 `main_backup` 整文件覆盖 C 类 | 丢失上游新功能 |
| 删除 `trading_agent` 包，逻辑塞回 main_window | 下次合并更痛 |
| 合并时保留旧版 `prompt_engineering` | 与上游 Schema 脱节 |
| 向 `upstream` 远程 push | 无权限且破坏协作假设 |
| 冲突未清完就 commit | 运行时崩溃 |

---

## 6. 新增定制功能放哪里

（原则不变：先进 `pa_agent/trading_agent/` 等独立包，再在核心文件加接线。详见 `manifest.py`。）

---

## 7. 定制集成层模块速查

| 文件 | 职责 |
|------|------|
| `trading_agent/entry.py` | 应用入口：许可 → bootstrap → MainWindow |
| `trading_agent/bootstrap.py` | `enrich_app_context()` |
| `trading_agent/window_hooks.py` | 窗口标题、许可、notifier |
| `trading_agent/chart_live.py` | 图表实时更新开关 |
| `trading_agent/record_handlers.py` | 通知、持仓 tick |
| `trading_agent/licensing_ui.py` | 授权菜单与门禁 |
| `trading_agent/settings_ui.py` | 定制设置 UI |
| `trading_agent/manifest.py` | A/B/C 路径清单 |

---

## 8. 命令速查

```powershell
git checkout main
git pull origin main
git fetch upstream
git merge upstream/main
.\scripts\merge-upstream.ps1
python run.py
python -m pytest tests/unit -q
rg "<<<<<<<" pa_agent
```

---

## 9. 相关文档

| 文档 | 内容 |
|------|------|
| `docs/上游合并策略.md` | 策略摘要 |
| `docs/项目交接文档.md` | 模块总览 |
| `pa_agent/trading_agent/manifest.py` | A/B/C 路径清单 |

---

## 10. 提交信息约定

```
merge upstream/main YYYY-MM-DD
```

---

*文档版本：2026-06-15 · 生产分支：`main`*
