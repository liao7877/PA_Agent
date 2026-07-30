# 本地配置说明

本目录下的**运行时文件**默认已被 `.gitignore` 忽略，不会进入 Git 仓库。

## 首次使用

1. 复制模板为本地配置：

   ```cmd
   copy config\settings.example.json config\settings.json
   ```

2. 启动程序，在 **设置** 中填写你的 **API Key**（会加密写入 `api_key_encrypted`）。

   也可直接编辑 `config/settings.json` 中的 `base_url`、`model` 等字段，Key 仍建议通过 GUI 保存以便自动加密。

3. `config/exception_state.json` 由程序在需要时自动创建，一般无需手动复制。结构可参考 `exception_state.example.json`。

## `settings.json` 字段说明

| 字段 | 说明 |
|------|------|
| `provider.model` | 模型名称（须与网关支持的名称一致） |
| `provider.base_url` | OpenAI 兼容 API 根地址（DeepSeek 官方为 `https://api.deepseek.com`；部分代理需带 `/v1` 后缀，以网关文档为准） |
| `provider.api_key_encrypted` | 加密后的 Key；留空表示未配置 |
| `provider.thinking` | 是否启用思考/推理类扩展参数（依模型与网关而定） |
| `provider.reasoning_effort` | `low` / `medium` / `high` / `max` |
| `provider.context_window` | 用于上下文占用提示的窗口大小（tokens） |
| `general.last_data_source` | K 线数据来源：`mt5` / `tradingview` |
| `general.last_tradingview_exchange` | TradingView 现货黄金默认 `OANDA`（品种 `XAUUSD`） |
| `general.last_symbol` | 默认品种，须与 MT5「市场报价」名称一致（含 `m` 等后缀） |
| `general.last_timeframe` | 默认周期，如 `5m`、`15m`、`1h` |
| `general.decision_stance` | 阶段二倾向：`conservative` / `balanced` / `aggressive` / `extreme_aggressive` |
| `general.auto_resume_chart_after_analysis` | 分析结束后是否自动恢复「图表实时更新」（默认 `true`） |
| `general.mt5_terminal_path` | MT5 安装目录或 `terminal64.exe` 完整路径；空=自动连接 |
| `general.mt5_initialize_attempts` | MT5 初始化/授权就绪的最大尝试次数，默认 `3` |
| `general.mt5_initialize_backoff_initial_ms` | 首次重试等待，默认 `500ms`，之后指数退避 |
| `general.mt5_initialize_backoff_max_ms` | 初始化退避上限，默认 `5000ms` |
| `general.mt5_request_timeout_ms` | 单次串行 MT5 IPC 请求超时，默认 `10000ms` |
| `general.mt5_readiness_timeout_ms` | 预留的 MT5 就绪总时限设置，默认 `10000ms` |

MT5 数据接口由进程内单一 owner worker 串行调用；GUI 启动不进行同步连接。终端尚在登录、授权失败或会话断开时，后台刷新会有界重试并在恢复后重新选择仍被 source 持有的品种。该连接层只提供行情读取，不会自行调用下单、改单、平仓或撤单 API。

## 安全提醒

- **不要**将 `config/settings.json`、`config/exception_state.json` 提交到 Git。
- 若曾误提交 API Key，请立即在服务商处**作废并轮换**密钥。
- 建议在仓库根目录执行：`powershell -ExecutionPolicy Bypass -File tools\setup_git_secrets.ps1`
