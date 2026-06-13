# 实施计划：AI K线分析程序（ai-kline-analyzer）

## 概述

本计划把 `design.md` 中已批准的高层 / 低层设计转换为一系列可由编码代理增量执行的提示词。每一步都建立在前一步之上，并以"接线集成"收尾，确保不会留下悬挂、未被任何上游引用的代码。任务范围严格限定为编写、修改或测试代码；用户验收测试、生产环境部署、性能压测、运行整套 GUI 做端到端人工演练等不在内。

实施根目录：`D:\cl\PA_Agent\`，源码放在 `pa_agent/` 包下，记录、经验、配置、日志等运行期产物各自在同级目录中。所有依赖（PyQt6、pyqtgraph、tvdatafeed、openai、tiktoken、jsonschema、pydantic、cryptography、pytest、hypothesis、pytest-qt 等）由 §1 中的依赖清单统一声明。

依赖关系顺序：项目骨架 → 配置 → 安全 → 数据层 → 指标 → AI 客户端 → 提示词与路由 → JSON 校验 → 异常计数器 → 记录持久化 → 双阶段编排 → 自由聊天 → GUI（共享 / 主页 / 对话页 / 调试页）→ 线程与切换 → 日志脱敏 → 端到端冒烟 → 打包与开发体验。

任务命名约定：

- `- [ ] N.M ...` 为必做任务，编码代理 **必须** 实现。
- `- [ ]* N.M ...` 为可选任务（主要是各类测试与 PyInstaller 打包），编码代理 **不会** 自动实现，可被显式跳过。
- 每个叶子任务末尾以括号列出其覆盖的需求条目（例如 `(R7.3, PR1.1)`）；性质化测试任务恰好引用一个 `PR*`。

> 子代理执行说明（来自工作流模板，逐字保留）：
> Convert the feature design into a series of prompts for a code-generation LLM that will implement each step with incremental progress. Make sure that each prompt builds on the previous prompts, and ends with wiring things together. There should be no hanging or orphaned code that isn't integrated into a previous step. Focus ONLY on tasks that involve writing, modifying, or testing code.

---

## 任务列表

- [x] 1. 项目骨架与依赖
  - [x] 1.1 在 `D:\cl\PA_Agent\` 创建 `pyproject.toml`（首选）或 `requirements.txt`，固定版本：`PyQt6>=6.6`、`pyqtgraph>=0.13`、`numpy>=1.26`、`pandas>=2.2`、`openai>=1.40`、`tiktoken>=0.7`、`jsonschema>=4.22`、`pydantic>=2.7`、`tvdatafeed`、`cryptography>=42`、`pywin32; sys_platform == 'win32'`，开发依赖 `pytest>=8`、`hypothesis>=6`、`pytest-qt`，并配置 `ruff` + `black` 作为格式化/静态检查工具链；包名为 `pa_agent`，最低 Python 版本 3.11。 (R0 隐含 / 设计 §8)
  - [x] 1.2 按 design §B.1 创建 `pa_agent/` 包目录树（`gui/`、`gui/widgets/`、`data/`、`indicators/`、`ai/`、`ai/prompts/`、`orchestrator/`、`records/`、`config/`、`security/`、`util/`），为每个目录创建空 `__init__.py`。 (R2.1)
  - [x] 1.3 创建运行期目录占位：`D:\cl\PA_Agent\records\pending\`、`D:\cl\PA_Agent\experience\{micro_channel,tight_channel,normal_channel,broad_channel,spike,trading_range,trending_tr,extreme_tr,unknown}\{success_cases,failure_cases}\`、`D:\cl\PA_Agent\config\`、`D:\cl\PA_Agent\logs\`，每个空目录下放一个 `.gitkeep`。 (R12.1, R13.1, R17.1)
  - [x] 1.4 实现 `pa_agent/main.py`：构造 `QApplication`，打开一个空的 `QMainWindow` 标题为 "Trading Agent"，作为后续启动入口与冒烟目标；`if __name__ == "__main__": main()` 风格。 (R10.1, R16.1)
  - [x] 1.5 实现 `pa_agent/app_context.py`：定义 `AppContext` 数据类承载 `Settings`、共享 `Logger`、共享 `EventBus` 占位字段，`main.py` 装配并传入 `MainWindow`，避免后续模块拿全局单例。 (R10.1, R16.1, R16.2)

- [ ] 2. 配置与路径常量
  - [x] 2.1 实现 `pa_agent/config/paths.py`：导出常量 `PROJECT_ROOT`、`PROMPT_DIR`、`PA_AGENT_DIR`、`RECORDS_PENDING_DIR`、`EXPERIENCE_DIR`、`CONFIG_DIR`、`LOGS_DIR`、`SETTINGS_JSON_PATH`、`EXCEPTION_STATE_JSON_PATH`、`LOG_FILE_PATH`，全部以 `pathlib.Path` 表示并指向 `D:\cl\PA_Agent\` 子树。 (R12.1, R8.3, R17.1, R17.2)
  - [x] 2.2 实现 `pa_agent/config/settings.py`：用 pydantic v2 定义 `PricingTable`、`AIProviderSettings`、`GeneralSettings`、`Settings`，默认值与 design §B.2.7 / R4.2 完全一致（`model="deepseek-v4-pro"`、`base_url="https://api.deepseek.com"`、`thinking=True`、`reasoning_effort="max"`、`context_window=1_000_000`、`pricing.input_cache_hit=0.1`、`input_cache_miss=12.0`、`output=24.0`、`default_bar_count=200`、`refresh_interval_ms=1000`、`cost_warning_threshold_pct=80`、`last_symbol="XAUUSD"`、`last_timeframe="1h"`、`last_htf_text=""`）。 (R4.1, R4.2, R10.4, R10.5, R15.1)
  - [x] 2.3 在 `pa_agent/config/settings.py` 中实现 `load_settings(path) -> Settings` 与 `save_settings(settings, path) -> None`，写盘时把 `provider.api_key`（明文，运行内存字段）经 `SecretStore.encrypt()` 转为 `provider.api_key_encrypted` 后再序列化；读取时反向解密回内存字段，缺省文件时落地默认 `Settings`。 (R4.3, R4.6, R17.1)
  - [x] 2.4 编写 `tests/unit/test_settings_round_trip.py` 覆盖：默认值、`save → load` 后字段全等、API key 仅以 `api_key_encrypted` 落盘且不含明文、读取空文件落入默认 `Settings`。 (R4.3, R4.6, R17.1, PR6)

- [x] 3. 安全 / SecretStore
  - [x] 3.1 实现 `pa_agent/security/secret_store.py`：`SecretStore.encrypt(plaintext: str) -> str` 与 `decrypt(ciphertext: str) -> str`；Windows 平台用 `pywin32.win32crypt.CryptProtectData / CryptUnprotectData`（DPAPI），其它平台用 `cryptography.fernet.Fernet` + 用户目录下随机生成的 keyfile（首次运行落地）；密文统一以 `base64` 字符串返回。 (R17.1)
  - [x] 3.2 实现 `mask_secret(s: str) -> str`：长度 ≥ 4 时返回 `"*" * (len(s) - 4) + s[-4:]`，长度 < 4（含空串）时原样返回；导出为 `pa_agent.security.secret_store.mask_secret`。 (R17.6, R4.5)
  - [x] 3.3 编写 `tests/unit/test_secret_store_roundtrip.py`：随机字符串经 `encrypt → decrypt` 后等于原文；非法密文 `decrypt` 抛 `ValueError`；不同平台分支通过 `monkeypatch` 强制切换。 (R17.1)
  - [x] 3.4 编写 `tests/property/test_mask_secret.py` 用 hypothesis 覆盖：所有长度 ≥ 4 的字符串末四位与原始一致且前缀全为 `*`；长度 < 4 时输出等于输入；脱敏函数对任意输入永不抛异常。 (R17.6, PR6)

- [x] 4. 数据层
  - [x] 4.1 实现 `pa_agent/data/base.py`：`@dataclass(frozen=True)` 定义 `KlineBar`、`KlineFrame`、`IndicatorBundle`，并定义 `DataSource` ABC，至少声明 `connect / disconnect / list_symbols / supported_timeframes / subscribe / unsubscribe / latest_snapshot(n)` 七个抽象方法，签名与 design §B.2.1 一致。 (R2.1, R2.4, R7.1, R7.2)
  - [x] 4.2 实现 `pa_agent/data/tradingview.py`：`TradingViewSource(DataSource)` 通过 `tvdatafeed` 实现 `connect / list_symbols / supported_timeframes / subscribe(symbol, timeframe) / unsubscribe / latest_snapshot(n)`；`latest_snapshot` 必须把当前未收盘 bar 作为 `seq=1` 返回（依赖 `tvDatafeed.get_hist(..., n_bars=n+1)` 并把头部标记为 `closed=False`）；网络异常需抛 `DataSourceTransientError` 而不是冒泡。 (R1.1, R1.5, R2.2, R7.2)
  - [x] 4.3 实现 `pa_agent/data/mt5.py`：`MT5Source(DataSource)` 类签名完整，但所有方法体 `raise NotImplementedError("MT5 source is a stub; see design §B.20")`；预留 `from MetaTrader5 import ...` 的注释占位。 (R2.3, R2.5)
  - [x] 4.4 实现 `pa_agent/data/kline_buffer.py`：`KlineBuffer(capacity: int)` 提供 `append(bar)`、`update_forming(bar)`、`last_n_including_forming(n)`、`clear()`、`snapshot_view()`，内部以"已收盘列表 + 单一未收盘 head"两段存储，所有公开方法持有 `threading.RLock`，扩容/裁剪时严格保持时间倒序。 (R1.3, R7.6, R3.1, R16.4)
  - [x] 4.5 实现 `pa_agent/data/snapshot.py::take_snapshot(buffer, n) -> KlineFrame`：在锁内取最近 `n` 根（含未收盘 head），按 `i ∈ [0, n-1)` 赋 `seq=i+1`，head 的 `closed=False`，其余 `closed=True`；调用 `compute_indicators(bars)` 填好 `IndicatorBundle`，整体深拷贝为不可变 `KlineFrame`，写入 `snapshot_ts_local_ms = util.timefmt.now_local_ms()`。 (R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, PR1.1)
  - [x] 4.6 实现 `pa_agent/data/refresh_loop.py::RefreshLoop(QThread)`：`run()` 每 `general.refresh_interval_ms` 调用 `data_source.latest_snapshot(N+5)`，把结果合并进 `KlineBuffer`，通过 `pyqtSignal(KlineFrame)` 推给 UI；连续 5 秒失败则发 `pyqtSignal(str)` 通知状态栏 "数据延迟"，永不冒泡未捕获异常；尊重 `cancel_token`。 (R1.2, R1.6, R16.1, R16.6)
  - [x] 4.7 编写 `tests/unit/test_kline_buffer.py`：覆盖 capacity 截断、`update_forming` 不会改变已收盘段、`last_n_including_forming` 在 head 翻转瞬间不返回重复 `ts_open`、清空后再灌入正常工作。 (R1.3, R3.1, R7.6)
  - [x] 4.8 编写 `tests/property/test_snapshot_bijection.py`：用 hypothesis 生成 `n ∈ [2, 200]` 与 `[n, n+50]` 长度的合成 buffer，断言 `take_snapshot(buffer, n)` 满足：长度 == n、序号集合 == {1..n}、`bars[0].seq==1 ∧ closed==False`、`ts_open` 严格倒序、与原 buffer 字段位完全一致（深拷贝不变）。 (PR1.1)

- [x] 5. 指标
  - [x] 5.1 实现 `pa_agent/indicators/ema.py`：`ema_full(values: list[float], period: int) -> list[float]`，前 `period-1` 项为 `nan`，第 `period` 项为简单均值，其后用 `prev*(1-α) + cur*α`，`α=2/(period+1)`；`ema_incremental(state: EmaState, x: float) -> EmaState` 维护单点滚动；`EmaState` 是 `@dataclass(frozen=True)`。 (R1.3, R5.2, PR8.1)
  - [x] 5.2 实现 `pa_agent/indicators/atr.py`：`atr_full(highs, lows, closes, period=14) -> list[float]` 用 Wilder 平滑，前 `period-1` 项为 `nan`；`atr_incremental(state, high, low, close) -> AtrState`；同样导出 `AtrState`。 (R1.3, R5.2, PR8.1)
  - [x] 5.3 在 `pa_agent/data/snapshot.py` 中导出 `compute_indicators(bars) -> IndicatorBundle`，调用 `ema_full` 与 `atr_full` 并按 `seq` 与 `bars` 完全对齐，返回 tuple，确保未收盘 bar 使用其当前 OHLC 计算。 (R5.2, R7.5)
  - [x] 5.4 编写 `tests/property/test_indicators_incremental.py` 覆盖 PR8：用 hypothesis 生成长度 `>= period` 的浮点序列与单点 `x`，断言 `ema_full(v + [x])[-1] ≈ ema_incremental(state_after(v), x).last`、`atr` 同理；NaN 仅出现在前 `period-1` 项；同输入两次产出深度相等。 (PR8.1)

- [x] 6. AI 客户端
  - [x] 6.1 实现 `pa_agent/ai/deepseek_client.py::DeepSeekClient`：构造接受 `AIProviderSettings` 与 `Logger`；`chat(messages, *, thinking=True, reasoning_effort="max", context_window=1_000_000, cancel_token=None, timeout_s=600) -> AIReply`，使用 `openai.OpenAI(base_url=..., api_key=...)`，调用时**只**传 `model`、`messages`、`extra_body={"thinking": {"type": "enabled"|"disabled"}, "reasoning_effort": <effort>}`、`timeout`，**禁止**出现 `temperature`、`top_p`、`presence_penalty`、`frequency_penalty`；记录 `latency_ms` 与 `request_id`，把响应包成 `AIReply(content, reasoning_content, raw, usage, request_id, latency_ms)`；写日志前用 `mask_secret` 屏蔽 `Authorization`。 (R5.8, R15.5, R17.2, R17.3)
  - [x] 6.2 实现 `pa_agent/ai/token_counter.py`：`estimate_tokens(messages: list[dict], model_hint: str = "cl100k_base") -> int`，加载 `tiktoken.get_encoding("cl100k_base")` 编码 `system + user` 字符串求和，向上取整；导出便于 Tab3 "预估 vs 实际"。 (R15.6)
  - [x] 6.3 实现 `pa_agent/ai/cost_estimator.py::estimate_cost(usage: AIUsage, pricing: PricingTable) -> float`：按 `(hit*input_cache_hit + (prompt-hit)*input_cache_miss + completion*output) / 1_000_000` 计算，单位人民币；同时导出 `breakdown(usage, pricing) -> dict` 返回三段费用明细供 UI 展示。 (R10.4, R15.2)
  - [x] 6.4 实现 `pa_agent/ai/session_ledger.py::SessionTokenLedger`：维护 `total_input / total_cached_input / total_output / total_cny / context_used`；`add(usage)` 累加并按 80% / 95% 阈值发出 `pyqtSignal(level, payload)`；`reset()` 与 `breakdown()` 用于切换会话与 UI 渲染。 (R10.4, R10.5, R15.1, R15.3, R15.4, R11.7)
  - [x] 6.5 编写 `tests/unit/test_deepseek_client.py`：用 `unittest.mock` 替换 `openai.OpenAI`；断言调用参数中**绝对不**含 `temperature/top_p/presence_penalty/frequency_penalty`；`extra_body.thinking.type` 与 `reasoning_effort` 与设置一致；`cancel_token` 置位时 `chat` 提前返回或抛 `CancelledError`；日志中无明文 API key。 (R5.8, R15.5, R17.2, PR6)
  - [x] 6.6 编写 `tests/unit/test_cost_and_ledger.py`：固定 `PricingTable` 与 `AIUsage`，断言 `estimate_cost` 与 design §B.9 公式逐位等价；多次 `add` 后阈值在 80% / 95% 处分别触发恰好一次黄/红事件。 (R10.4, R10.5, R15.1, R15.2, R15.3, R15.4)

- [x] 7. Prompt 拼装与策略路由
  - [x] 7.1 实现 `pa_agent/ai/prompt_assembler.py::PromptAssembler`：构造接受 `prompt_dir: Path`（固定为 `D:\cl\PA_Agent\prompt_engineering\`）与 `experience_reader`；提供 `build_stage1(frame, htf_text) -> list[dict]`、`build_stage2(frame, stage1_json, strategy_files, experience_entries) -> list[dict]`、`stage2_system_prompt_only(...) -> str`；阶段一系统提示拼接顺序严格为 `提示词大纲_人设与思维方式.txt` → `市场诊断框架.txt` → `文件16-K线信号识别.txt` → 阶段一输出格式提醒；阶段二系统提示按 人设 → 路由策略文件 → `文件17-止损和止盈与仓位管理.txt` → 经验库 → 决策输出契约（含"不下单时三价段位必须为 null"的显式声明）；用户提示按 design §B.3 渲染 K 线表与指标表。 (R5.1, R5.2, R5.5, R5.6, R6.2)
  - [x] 7.2 实现 `pa_agent/ai/router.py::route_strategy_files(stage1_json) -> list[str]`：完全遵循 R14.2–R14.12 的顺序与去重规则；对中性方向通道与中性方向 spike 调用 `logger.warning`；对 `extreme_tr / unknown` 仅可能因形态追加文件；最终经稳定去重（保留首次出现）；纯函数，禁止访问外部状态。 (R14.1, R14.2, R14.3, R14.4, R14.5, R14.6, R14.7, R14.8, R14.9, R14.10, R14.11, R14.12)
  - [x] 7.3 编写 `tests/unit/test_prompt_assembler.py`：断言阶段一系统提示按 design §B.3 顺序拼接、user prompt 含 symbol/timeframe/N/EMA20/ATR14/HTF/JSON 输出要求；阶段二系统提示按"人设 → 策略 → 风控 → 经验 → 契约"顺序；`htf_text=""` 时仍保留段落占位。 (R5.1, R5.2, R5.5, R5.6, R6.2, R6.3)
  - [x] 7.4 编写 `tests/property/test_router_determinism.py` 覆盖 PR2：用 hypothesis 生成合法 `stage1_json`，断言 `route(s) == route(s)`、元素全部位于 17 文件清单内、列表稳定去重、`route(deepcopy(s))` 与 `route(s)` 字符串字位一致。 (PR2.1)

- [x] 8. JSON 校验
  - [x] 8.1 实现 `pa_agent/ai/prompts/schemas.py`：以 Python 字典常量定义 `STAGE1_SCHEMA` 与 `STAGE2_SCHEMA`，分别对应 design §B.7.1、§B.7.2，包括 `allOf` 中的 `if/then` 条件（`spike`/`micro_channel` 要求 `spike_stage`、`market_phase=transitioning` 要求 `transition_risk`、不下单时四字段为 `null`、有下单时四字段非 null 且 `order_direction ∈ {做多,做空}`）。 (R5.3, R5.7, R9.1, R9.2)
  - [x] 8.2 实现 `pa_agent/ai/json_validator.py::JsonValidator`：`validate(stage: Literal["stage1","stage2"], raw_text: str) -> Result`；流程为 `strip_markdown_fences → json.loads → jsonschema.iter_errors`；按 design §B.7 校验流水线分别归类 a 语法 / b 缺字段 / c 值非法 / d 纯文本；返回 `Ok(obj)` 或 `ValidationError(category, missing_fields, invalid_fields, raw_text, parse_position)`。 (R5.3, R5.7, R8.1, R8.2, R8.6)
  - [x] 8.3 在 `JsonValidator` 中显式增加阶段二的"不下单 ↔ 三价 + 方向全为 null"双向铁律：当 schema 因 `if/then` 失败时把 `category` 强制设为 `c`，`invalid_fields` 字段精准列出 `entry_price / take_profit_price / stop_loss_price / order_direction` 与允许值集合。 (R9.1, R9.2, R9.3, PR3.1)
  - [x] 8.4 编写 `tests/property/test_json_validator_categories.py` 覆盖 PR7：用 hypothesis 生成 4 类突变体（合法、缺字段、值非法、纯文本），断言 `validate` 返回正确的 `category`，且对合法 JSON 返回 `Ok` 并保持字段顺序。 (PR7.1)
  - [x] 8.5 编写 `tests/property/test_stage2_no_order_invariant.py` 覆盖 PR3：用 hypothesis 在 `decision.order_type` 与四字段值（含 0、负数、字符串、None）的笛卡尔积上断言 `validate` 严格执行不下单与有下单两侧规则。 (PR3.1)

- [x] 9. 持久化连续异常计数器
  - [x] 9.1 实现 `pa_agent/orchestrator/exception_counter.py::ExceptionCounter`：构造接受 `state_path: Path`（默认 `paths.EXCEPTION_STATE_JSON_PATH`）；`load()` 与 `save()` 读写 `{consecutive_count, last_error_category, last_error_at_ms, history(<=50)}`；缺省文件时返回零状态。 (R8.3, R8.5)
  - [x] 9.2 在 `ExceptionCounter` 中实现 `on_validation_error(stage, err)` 自增 + `push_history`、`on_round_trip_success()` 置零、`on_user_cancel(reason)` 与 `on_network_error(err)` 都为 no-op（只追加 history，不动 `consecutive_count`）；`raise_alarm(stage, err, state, is_streak)` 通过注入的 `event_bus.emit("exception", AlarmPayload)` 通知 UI。 (R8.3, R8.4, R8.6, R8.7, R8.8, R8.9, R3.3, R11.6, R18.1, R18.2, R18.3, R18.6)
  - [x] 9.3 编写 `tests/property/test_exception_counter_monotone.py` 覆盖 PR4：用 hypothesis 生成由 `ValidationError | RoundTripSuccess | UserCancel | NetworkError` 组成的事件序列，断言：失败事件后计数单调非减；`RoundTripSuccess` 立即置零；`UserCancel/NetworkError` 不改变计数；`save → 重新构造 ExceptionCounter → load` 后状态完全相等。 (PR4.1)

- [x] 10. 记录持久化
  - [x] 10.1 实现 `pa_agent/records/schema.py`：用 pydantic 定义 `RecordMeta`、`AnalysisRecord`、`FollowupTurn`、`AlarmPayload`、`ValidationError`、`ExperienceEntry`，字段集合与 design §B.2.6 / §B.15 完全一致，并配置 `model_config = ConfigDict(extra="forbid")`。 (R12.2, R12.4, R8.6)
  - [x] 10.2 实现 `pa_agent/records/pending_writer.py::PendingWriter`：`save_full(record) -> Path`、`save_partial(record, reason: str) -> Path`、`append_followup(record_id, turn) -> None`；文件名 `{YYYY-MM-DD_HH-mm-ss}_{symbol}_{timeframe}.json`，时间戳取自 `record.meta.timestamp_local_ms`；`append_followup` 写到 `<basename>.followups.jsonl`；磁盘失败时记录到日志和事件总线，不冒泡。 (R12.1, R12.4, R12.6, R3.5)
  - [x] 10.3 在 `PendingWriter` 内置脱敏管线：序列化前对整个 `record.dict()` 递归扫描字符串字段，把任何与运行内存中 `provider.api_key` 完全相同的子串替换为 `mask_secret(provider.api_key)`，保证 `meta.ai_provider` 与任意 `messages` 中都不会泄漏明文。 (R12.3, R17.3, PR6.1)
  - [x] 10.4 实现 `pa_agent/records/experience_reader.py::ExperienceReader.read_top5(cycle_position) -> list[ExperienceEntry]`：扫描 `success_cases / failure_cases` 目录，按文件名内嵌 `YYYY-MM-DD_HH-mm-ss` 解析为毫秒时间戳并降序，取前 5；目录缺失返回空列表；解析失败的文件名记 warning 并跳过；只读，不写不删。 (R13.1, R13.2, R13.3, R13.4, R13.5)
  - [x] 10.5 编写 `tests/property/test_record_round_trip.py` 覆盖 PR5：用 hypothesis 生成 `AnalysisRecord`（含 `kline_data` 浮点、`reasoning_content`、可选字段），断言 `AnalysisRecord.model_validate(json.loads(json.dumps(r.model_dump()))) == r` 深度相等。 (PR5.1)
  - [x] 10.6 编写 `tests/unit/test_pending_writer_no_plaintext_key.py` 覆盖 PR6：构造一个含明文 key 的 `AnalysisRecord`（在 `meta.ai_provider` 与某条 message 字符串里），断言落盘后的文件读回作为字符串后**不**包含该明文，但**包含** `mask_secret` 形态。 (PR6.1)

- [x] 11. 双阶段编排器
  - [x] 11.1 实现 `pa_agent/util/threading.py`：`CancelToken`（`set / is_set / wait(timeout)`，基于 `threading.Event`）与 `OrchestratorEvent` 枚举（`Stage1Started/Stage1Done/Stage1Failed/Stage2Started/Stage2Done/Stage2Failed/RecordSaved/Cancelled`）。 (R3.2, R11.6, R16.5)
  - [x] 11.2 实现 `pa_agent/orchestrator/two_stage.py::TwoStageOrchestrator.submit(frame, htf_text, settings, cancel_token, on_event) -> AnalysisRecord`：流程串接 `prompt_assembler.build_stage1` → `client.chat` → `validator.validate("stage1", ...)` → 失败则 `exc_counter.on_validation_error` + `pending_writer.save_partial` 终止，成功则 `router.route_strategy_files` → `experience_reader.read_top5` → `prompt_assembler.build_stage2` → `client.chat` → `validator.validate("stage2", ...)` → 同样的失败/成功路径；只在两阶段都成功时调用 `exc_counter.on_round_trip_success` 与 `pending_writer.save_full`；每个阶段开始/结束触发对应 `on_event`。 (R5.1, R5.3, R5.4, R5.5, R5.7, R8.2, R8.4, R12.1, R12.2, R18.4)
  - [x] 11.3 在 `submit` 全程检查 `cancel_token.is_set()`：进入每个阶段前、API 返回后均检查；命中即调用 `pending_writer.save_partial(reason="user_cancelled")` + `exc_counter.on_user_cancel(...)`，触发 `OrchestratorEvent.Cancelled`，不增加 `consecutive_count`。 (R3.2, R3.3, R3.5, R8.8, R11.6, R16.5)
  - [x] 11.4 编写 `tests/integration/test_two_stage_happy_path.py`：用 mock `DeepSeekClient` 返回合法阶段一/二 JSON，断言落盘记录字段齐全、`exc_counter.consecutive_count == 0`、事件流为 `Stage1Started, Stage1Done, Stage2Started, Stage2Done, RecordSaved`。 (R5.1, R5.4, R12.1, R12.2)
  - [x] 11.5 编写 `tests/integration/test_two_stage_stage1_syntax.py`：mock 客户端返回非 JSON 文本，断言 `consecutive_count` 自增 1、`save_partial("stage1_invalid_json")` 被调用、`Stage2Started` 事件不应出现。 (R8.1, R8.3, R18.1)
  - [x] 11.6 编写 `tests/integration/test_two_stage_stage1_missing_field.py`：mock 客户端返回缺 `cycle_position` 的 JSON，断言归类为 b 并自增计数。 (R8.1, R8.3, R5.3)
  - [x] 11.7 编写 `tests/integration/test_two_stage_stage2_invalid_value.py`：mock 客户端阶段二返回 `confidence="ultra"`，断言归类为 c 并自增计数。 (R8.1, R8.3, R5.7)
  - [x] 11.8 编写 `tests/integration/test_two_stage_no_order_with_prices.py`：mock 客户端阶段二返回 `order_type="不下单"` 但 `entry_price=0`，断言被归类为 c 并自增计数。 (R9.3, R8.1, PR3.1)
  - [x] 11.9 编写 `tests/integration/test_two_stage_network_timeout.py`：mock 客户端抛 `openai.APITimeoutError`，断言归类为网络/超时、`consecutive_count` 不变、Tab3 事件被发出。 (R8.9, R18.6)
  - [x] 11.10 编写 `tests/integration/test_two_stage_user_cancel.py`：在阶段二开始前置位 `cancel_token`，断言 `Cancelled` 事件、`save_partial("user_cancelled")` 被调用、`consecutive_count` 不变。 (R3.2, R3.3, R8.8, R11.6)

- [x] 12. 自由聊天会话
  - [x] 12.1 实现 `pa_agent/orchestrator/free_chat.py::FreeChatSession`：构造接受 `base_record`、`client`、`assembler`、`pending_writer`、`ledger`；`send(user_text, cancel_token) -> AIReply` 按 design §B.17 维护 `history_full`（保留 `reasoning_content`）与 `history_for_api`（默认丢弃 `reasoning_content`）；调用 `client.chat(history_for_api, thinking=True, reasoning_effort=settings.reasoning_effort)` 后追加到 `history_full` 与持久化。 (R11.2, R11.3, R11.4)
  - [x] 12.2 在 `FreeChatSession` 暴露开关 `keep_reasoning_in_resend: bool = False`；为 True 时在 `history_for_api` 中保留旧 assistant 消息的 `reasoning_content`，预留给将来的工具调用场景；当前默认 False。 (R11.5)
  - [x] 12.3 在 `send` 末尾调用 `ledger.add(reply.usage)` 与 `pending_writer.append_followup(record_id, turn=...)`；用户点击"停止"时通过 `cancel_token` 触发 `cancelled=True` 的 `FollowupTurn` 落盘且不动 `consecutive_count`。 (R11.6, R11.7, R12.4)
  - [x] 12.4 编写 `tests/unit/test_free_chat_resend_drops_reasoning.py`：在默认开关下连发 3 轮，断言 `history_for_api` 中 assistant 消息的 `reasoning_content` 被丢弃，`history_full` 中保留全部。 (R11.4, R11.5)
  - [x] 12.5 编写 `tests/unit/test_free_chat_keeps_reasoning_when_toggled.py`：`keep_reasoning_in_resend=True` 时 `history_for_api` 保留 `reasoning_content`；`append_followup` 落盘的 JSONL 行始终包含 `ai_reasoning` 字段。 (R11.4, R11.5, R12.4)

- [x] 13. GUI：共享框架
  - [x] 13.1 实现 `pa_agent/gui/main_window.py::MainWindow(QMainWindow)`：装配 `QTabWidget` 含三个 Tab（"主页"、"对话页"、"调试页"），状态栏 `QStatusBar` 显示订阅/分析/数据延迟文本，菜单项进入 `SettingsDialog`。 (R10.1, R10.2, R1.6)
  - [x] 13.2 实现 `pa_agent/util/event_bus.py::EventBus`：基于 `pyqtSignal` 暴露 `data_frame(KlineFrame)`、`status(str)`、`exception(AlarmPayload)`、`token_update(dict)` 等通道；`MainWindow` 在 init 阶段把对应 slot 接到状态栏与各 Tab。 (R8.6, R10.5, R15.3, R18.1, R18.3)
  - [x] 13.3 实现 `pa_agent/gui/settings_dialog.py::SettingsDialog`：表单字段 `model / base_url / api_key（QLineEdit.Password）/ thinking / reasoning_effort / context_window / pricing.input_cache_hit / input_cache_miss / output / default_bar_count / refresh_interval_ms / cost_warning_threshold_pct / last_symbol / last_timeframe / last_htf_text`；保存时调用 `settings.save_settings()`，明文 key 永不出现在 `QLabel`，"显示"按钮临时切换到明文回显但不触发持久化。 (R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R17.4)

- [x] 14. GUI：Tab 1 主页
  - [x] 14.1 实现 `pa_agent/gui/widgets/candle_item.py`：基于 `pyqtgraph.GraphicsObject` 的自绘蜡烛项，红绿配色按 `close >= open`；`pa_agent/gui/widgets/seq_label_item.py`：基于 `pyqtgraph.TextItem` 的序号标签，文本为 `f"#{seq}"`；`pa_agent/gui/widgets/overlay_lines.py`：`InfiniteLine` + `TextItem` 组合，实现 entry / TP / SL 横线及标签。 (R1.4, R10.2)
  - [x] 14.2 实现 `pa_agent/gui/chart_widget.py::ChartWidget(pg.PlotWidget)`：`set_frame(frame: KlineFrame)` 渲染 N 根蜡烛 + EMA20 折线 + 序号标签；`set_decision(decision)` 仅当 `order_type ≠ 不下单` 时绘制 entry/TP/SL，否则清除已有横线；`reset()` 清空全部子项。 (R1.3, R1.4, R7.5, R9.4, R10.2)
  - [x] 14.3 实现 `pa_agent/gui/decision_panel.py::DecisionPanel`：当 `order_type == 不下单` 时只展示 `reasoning` 与不下单结论；否则展示方向 / 类型 / 入场 / 止盈 / 止损 / 简短理由；通过事件总线接收 `OrchestratorEvent.RecordSaved`。 (R9.5, R10.2)
  - [x] 14.4 在 `MainWindow` 中实现主页控件：Symbol 与 Timeframe 下拉、`BarCount` 输入（默认 200，范围 [2, 5000]）、HTF `QPlainTextEdit`、"提交分析" 按钮；按钮在 buffer 未满 N、分析中、切换中、`consecutive_count >= 2` 时灰显。 (R6.1, R6.2, R8.7, R10.2)
  - [x] 14.5 在 `ChartWidget` 旁挂一个 30 Hz `QTimer` 节流器：每 ~33 ms 把最近 `RefreshLoop.data_frame` 信号缓存的最新帧重绘一次，避免 1Hz 数据线程把绘制压力压回 UI 主线程。 (R16.4)
  - [x] 14.6 在主页接线 "提交分析" 按钮到 AI worker：实例化 `TwoStageOrchestrator`，把 `take_snapshot(buffer, BarCount)` 与 `htf_text` 传入；worker 完成后通过事件总线驱动 `ChartWidget.set_decision` 与 `DecisionPanel.set_decision`。 (R5.1, R6.2, R7.1, R10.2)
  - [x] 14.7 编写 `tests/unit/test_chart_widget_no_lines_when_not_trading.py` 用 pytest-qt：注入 `order_type="不下单"` 的决策，断言 `ChartWidget` 内不存在任何 `InfiniteLine` 项。 (R9.4, R10.2)

- [x] 15. GUI：Tab 2 对话页
  - [x] 15.1 实现 `pa_agent/gui/conversation_widget.py::ConversationWidget`：渲染 stage1/stage2 的 `reasoning_content` 与 `content`（默认折叠 reasoning）、自由聊天消息流；输入区为 `QPlainTextEdit` + 发送按钮，发送中按钮变为"停止"。 (R10.3, R11.4)
  - [x] 15.2 在 `ConversationWidget` 中实现"两阶段成功后才启用"的状态机：监听 `OrchestratorEvent.RecordSaved` 后启用输入；切换品种/周期或下一次提交开始时禁用并清空 `FreeChatSession`。 (R3.4, R11.1, R11.2)
  - [x] 15.3 实现"实时 Token 与费用指示器"：进度条显示 `context_used / context_window`，文本同时展示 `prompt_tokens + completion_tokens` 与百分比、按 `pricing.input_cache_hit / input_cache_miss / output` 分别核算的累计费用与总额；80% 切黄色、95% 切红色 + 一次性弹窗。 (R10.4, R10.5, R15.1, R15.3, R15.4)
  - [x] 15.4 把 `FreeChatSession` 接入 `ConversationWidget`：发送按钮调用 `FreeChatSession.send`，"停止"按钮触发 `cancel_token.set()`；每轮结果回到主线程后追加到消息流并刷新指示器。 (R11.3, R11.4, R11.6, R11.7)
  - [x] 15.5 编写 `tests/unit/test_token_indicator_thresholds.py` 用 pytest-qt：模拟累计 80%、95% 触发对应颜色与弹窗各一次。 (R10.5, R15.4)

- [x] 16. GUI：Tab 3 调试页
  - [x] 16.1 实现 `pa_agent/gui/debug_widget.py::DebugWidget`：左侧 `QListWidget` 列出本次会话所有轮次（`Stage1 / Stage2 / Followup-N`），右侧四块 `QTextEdit` 分别显示 system prompt、user prompt、原始响应（含 HTTP status / headers / body / `reasoning_content` / `content` / `usage` / `request_id`）、校验/重试/异常分类。 (R10.6, R18.5)
  - [x] 16.2 在 `DebugWidget` 实现按钮："复制 system"、"复制 user"、"复制 response"、"导出本轮 JSON"（写到 `records/pending/<basename>.debug-<turn>.json`）。 (R10.7)
  - [x] 16.3 在 `DebugWidget` 实现"清除连续异常计数"按钮：弹出 `QMessageBox.question` 确认，确认后调用 `ExceptionCounter.reset_streak()` 并写日志；按钮在非 `consecutive_count >= 2` 时仍可见但不强制使用。 (R8.7, R10.7, R18.3)
  - [x] 16.4 在 `DebugWidget` 渲染 `meta.ai_provider` 与每个原始响应文本前统一调用 `mask_secret`，且对完整 API 原文做一次 `replace(provider.api_key, mask_secret(...))`，确保任何形态下 API key 都不会被肉眼看到。 (R4.5, R17.3, PR6.1)
  - [x] 16.5 编写 `tests/unit/test_debug_widget_masks_key.py`：注入含明文 key 的 `AIReply`，断言 `DebugWidget` 任意 `QTextEdit.toPlainText()` 中均不含明文，但含 `mask_secret` 形态。 (R17.3, PR6.1)

- [x] 17. 线程与切换胶水
  - [x] 17.1 在 `MainWindow` 启动 `RefreshLoop` 于专用 `QThread`，AI worker 同样在专用 `QThread`：通过 `QObject.moveToThread` 与 `pyqtSignal` 接线；任何时刻最多一个 AI worker 实例存活。 (R16.1, R16.2, R16.3)
  - [x] 17.2 实现 `pa_agent/gui/main_window.py::MainWindow.on_symbol_or_tf_changed(new_symbol, new_tf)`：先 `cancel_token.set()` 取消当前 worker，5 秒内 `join` 否则标 zombie；调 `pending_writer.save_partial(reason="user_switched")`；`data_source.unsubscribe → buffer.clear → data_source.subscribe`；`ChartWidget.reset()`；销毁 `FreeChatSession`，Tab2 输入禁用；`ledger` 按设置选择 reset 或保留。 (R3.1, R3.2, R3.3, R3.4, R3.5, R16.5)
  - [x] 17.3 编写 `tests/integration/test_switch_mid_analysis.py` 用 pytest-qt + mock 客户端：在阶段二请求中触发 symbol 切换，断言 worker 在 100 ms 内取消、`consecutive_count` 不变、`save_partial("user_switched")` 被调用、`FreeChatSession` 已禁用。 (R3.2, R3.3, R3.5, R16.5)

- [x] 18. 日志与脱敏
  - [x] 18.1 实现 `pa_agent/util/logging.py::configure_logging()`：根 logger 装配 `RotatingFileHandler(LOG_FILE_PATH, maxBytes=5MB, backupCount=10)` 与控制台 handler；自定义 `MaskingFormatter` 在 `format()` 内对完整消息字符串调用 `replace(provider.api_key, mask_secret(...))`；`urllib3 / openai / httpx` 等三方 logger 都挂同一 handler，确保不被它们绕过。 (R17.2, R17.3, R17.5, PR6.1)
  - [x] 18.2 在 `pa_agent/main.py` 启动早期调用 `configure_logging()`，并在所有 `print` 入口替换为 `logger.info/debug`；`DeepSeekClient.chat` 写 debug 日志时走同一 logger。 (R17.2, R17.3)
  - [x] 18.3 编写 `tests/property/test_logs_have_no_plaintext_key.py` 覆盖 PR6：用 hypothesis 生成长度 ≥ 12 的伪 key，喂给 mock client 完整调用链；读取 `LOG_FILE_PATH` 全文后断言 key 明文 NOT IN file_text，但 `mask_secret(key)` 出现 ≥ 1 次。 (PR6.1)

- [x] 19. 端到端冒烟（可选但推荐）
  - [x] 19.1 在 `tests/e2e/test_smoke_happy_path.py` 用 pytest-qt 启动 `MainWindow`，注入 fake `DataSource`（按固定脚本喂 K 线）与 mock `DeepSeekClient`（按固定脚本返回 stage1/stage2），点击"提交分析"，断言：图表渲染 N 根 + EMA20 折线、`DecisionPanel` 显示有下单决策、`PendingWriter` 写出 JSON 文件。 (R1.1, R5.1, R7.1, R10.2, R12.1)
  - [x] 19.2 在 `tests/e2e/test_smoke_no_order.py` 喂 stage2 `order_type="不下单"`，断言图表无 entry/TP/SL 横线，`DecisionPanel` 仅显示 reasoning。 (R9.4, R9.5, R10.2)
  - [x] 19.3 在 `tests/e2e/test_smoke_switch_mid_flight.py` 在 stage2 进行中切换 symbol，断言 worker 取消、`consecutive_count` 不变、Tab2 输入框被禁用。 (R3.2, R3.3, R3.4, R16.5)
  - [x] 19.4 在 `tests/e2e/test_smoke_free_chat.py` 完成两阶段后在 Tab2 发送一条消息，断言 `FreeChatSession` 完成一轮、`<basename>.followups.jsonl` 多一行、`ledger` 累加。 (R11.2, R11.3, R11.7, R12.4)

- [x] 20. 打包与开发体验
  - [x] 20.1 编写 `D:\cl\PA_Agent\README.md`：包含项目说明、Windows 11 + Python 3.11 安装步骤、`python -m pa_agent.main` 启动命令、`pytest` / `pytest -m "not e2e"` 运行命令、目录结构概览、配置文件位置、常见问题。 (R0 隐含 / 设计 §7)
  - [x] 20.2 编写 `D:\cl\PA_Agent\Makefile`（或 `tasks.json`）暴露三个目标：`run`（启动 GUI）、`test`（`pytest -q`）、`lint`（`ruff check . && black --check .`）。 (R0 隐含 / 设计 §8)
---

## 备注

- 标 `*` 的任务为可选，主要包括各类单元测试、性质测试、集成测试与端到端冒烟；可在 MVP 阶段跳过，但保留任务条目方便后续补齐。
- 性质测试任务严格映射到 `requirements.md` §5 的 PR1–PR8，每条只引用一个 `PR*`；其它实现/单元测试任务使用 `R*` 引用，必要时同时引用多个。
- 实施严格按照"配置 → 安全 → 数据 → 指标 → AI 客户端 → 提示词 → 路由 → JSON 校验 → 异常计数 → 记录 → 编排 → 自由聊天 → GUI → 线程胶水 → 日志 → 端到端 → 打包"的顺序推进，确保后续任务都能调用前序模块、不存在悬挂代码。
- 任何对 `design.md` 与 `requirements.md` 的偏离必须先返回设计/需求阶段更新，再来调整本任务表。
