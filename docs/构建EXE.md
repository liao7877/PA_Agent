# Trading Agent 构建 Windows EXE 指南

本文说明如何将 **最新源码** 打包为 Windows 可执行程序，供技术人员与 AI Agent 按同一流程复现构建。

> 激活码签发、在线授权等见 [打包与授权.md](打包与授权.md)。

---

## Agent 快速指令（复制即用）

在 **项目根目录** `PA_Agent/` 下执行：

```powershell
# 正式发布推荐：Nuitka（逆向难度更高 + 嵌入式公钥）
powershell -ExecutionPolicy Bypass -File tools/build_windows_nuitka.ps1 -SkipTests

# 兼容构建：PyInstaller（开发/应急）
powershell -ExecutionPolicy Bypass -File tools/build_windows.ps1 -SkipTests

# PyInstaller + 安装包（需 Inno Setup 6）
powershell -ExecutionPolicy Bypass -File tools/build_windows.ps1 -Installer -SkipTests

# 干净重建
powershell -ExecutionPolicy Bypass -File tools/build_windows_nuitka.ps1 -Clean -SkipTests
```

**成功标志：**

- 控制台最后输出 `Build complete.`
- 存在 `dist/Trading_Agent/Trading_Agent.exe`
- 安全扫描输出 `Build safety check passed`
- 若带 `-Installer`，另存在 `dist/Trading_Agent_Setup.exe`

**失败时：** 不要手动改 `dist/` 里的文件；根据报错修复源码或环境后重新运行脚本（可加 `-Clean`）。

---

## 一、环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11（64 位） |
| Python | 3.11 或更高，`python` 在 PATH 中 |
| 网络 | 首次需 `pip install` 拉取依赖 |
| 可选 | [Inno Setup 6](https://jrsoftware.org/isinfo.php)（仅生成安装包时需要） |

建议在虚拟环境中构建：

```powershell
cd E:\Dev\Trading\PA_Agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

---

## 二、构建脚本说明

| 文件 | 作用 |
| --- | --- |
| `build.bat` | 双击或命令行入口，内部调用 `tools/build_windows.ps1` |
| `tools/build_windows_nuitka.ps1` | **正式发布推荐**：Nuitka 构建 + 嵌入式公钥同步 |
| `tools/build_windows.ps1` | PyInstaller 构建（兼容/应急） |
| `tools/sync_embedded_pubkey.py` | 将 `public_key.pem` 同步进 `embedded_pubkey.py` |
| `Trading_Agent.spec` | PyInstaller 规格 |
| `tools/verify_build_safe.ps1` | 扫描产物，防止误打包密钥与独立公钥文件 |
| `tools/installer.iss` | Inno Setup 安装包脚本（可选） |

### 脚本参数

| 参数 | 说明 |
| --- | --- |
| （无） | 默认：安装依赖 → 跑 `pytest tests/unit` → 打包 → 安全扫描 |
| `-Installer` | 额外生成 `dist/Trading_Agent_Setup.exe` |
| `-Clean` | 构建前删除 `build/` 与 `dist/Trading_Agent/` |
| `-SkipTests` | 跳过单元测试（应急用，正式发布不建议） |
| `-SkipInstall` | 跳过 `pip install -e .`（依赖已就绪时加快重复构建） |

### 构建流程（脚本内部顺序）

```text
检查 Python 版本 (>= 3.11)
    ↓
[可选 -Clean] 删除旧 build/dist
    ↓
pip install -e .  +  pyinstaller
    ↓
检查 pa_agent/licensing/public_key.pem 存在
    ↓
[默认] python tools/sync_embedded_pubkey.py
    ↓
[默认] pytest tests/unit
    ↓
PyInstaller 或 Nuitka
    ↓
verify_build_safe.ps1 扫描 dist/Trading_Agent
    ↓
[可选 -Installer] Inno Setup 编译 installer.iss
```

---

## 三、构建产物

### 仅 EXE 目录（默认）

```
dist/Trading_Agent/
├── Trading_Agent.exe          ← 主程序（无控制台窗口）
├── _internal/            ← PyInstaller 依赖与资源（须与 exe 同目录分发）
└── ...
```

**分发方式：** 将整个 `dist/Trading_Agent/` 文件夹打包为 zip 给客户，或在本机直接运行 `Trading_Agent.exe` 做冒烟测试。

### 安装包（加 `-Installer`）

```
dist/Trading_Agent_Setup.exe   ← 安装向导，默认装到 Program Files
```

安装后用户数据（配置、日志、授权）在 `%APPDATA%\Trading_Agent\`，不覆盖开发机上的 `config/settings.json`。

---

## 四、打包内容与安全边界

### 会打进包的内容

- `run.py` 入口及 `pa_agent` 全部 Python 包
- `prompt_engineering/` 提示词资源
- `config/settings.example.json`（首次运行复制到用户目录）
- `config/license_client.json` 或 `license_client.example.json`
- `pa_agent/gui/theme/dark.qss`
- `pa_agent/licensing/embedded_pubkey.py`（公钥哈希嵌入代码，**不再**随包分发独立 `.pem`）

### 绝不会打进包

- `config/settings.json`（含 API Key）
- `tools/.license_keys/license_private.pem`（私钥）
- `records/`、`logs/`、`experience/`
- 开发用测试与 `.git`

若新增资源目录（如图标、额外 JSON），需同步修改 `Trading_Agent.spec` 的 `datas` 列表。

### 打包前检查清单

- [ ] 已 `git pull` 或确认工作区为待发布版本
- [ ] 若轮换密钥：先 `python tools/license_keygen.py generate-keys`（会自动 sync 嵌入式公钥），再重新打包
- [ ] 本地 `config/settings.json` **不会**被包含（脚本会提示 Note）
- [ ] 需要在线授权时，在打包前创建 `config/license_client.json`（勿提交 Git）
- [ ] `pyproject.toml` 中 `version` 已按需更新（安装包 `installer.iss` 中 `MyAppVersion` 建议一并改）

---

## 五、构建后验证

1. **运行 exe（无需激活的冒烟方式有限）**  
   打包版首次启动会要求激活。开发机可先用源码 `python run.py` 验证功能，再测 exe 的激活流程。

2. **检查目录体积**  
   `dist/Trading_Agent/` 通常为数百 MB（含 PyQt6、numpy 等）。

3. **确认无密钥泄露**  
   脚本已自动执行 `verify_build_safe.ps1`；也可手动：

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\verify_build_safe.ps1
   ```

4. **在干净目录测试**  
   将 `dist/Trading_Agent` 复制到无 Python 的机器或新路径，双击 `Trading_Agent.exe`，确认能弹出激活窗或主界面。

---

## 六、常见问题

### `Python not found` / 版本过低

安装 [Python 3.11+](https://www.python.org/downloads/)，勾选 **Add to PATH**，重新打开终端。

### `Missing licensing public key`

```powershell
python tools/license_keygen.py generate-keys
```

私钥仅保留在 `tools/.license_keys/`，勿提交仓库。

### `Unit tests failed`

修复测试或临时 `-SkipTests`。**正式发布前必须测试通过。**

### PyInstaller 报 `ModuleNotFoundError` 相关模块

在 `Trading_Agent.spec` 的 `hiddenimports` 中补充模块名后重新构建。

### `Inno Setup 6 not found`

安装 Inno Setup 6，或去掉 `-Installer` 只产出 `dist/Trading_Agent/`。

### 客户机 SmartScreen 拦截

对 `Trading_Agent_Setup.exe` 做 **Authenticode 代码签名**（见 [打包与授权.md](打包与授权.md) 第九节）。

### 源码运行不需要激活，exe 需要

设计如此：打包版（PyInstaller/Nuitka）走授权校验。见 `pa_agent/licensing/packaged.py`。

---

## 七、相关工具（非主程序）

| 目标 | 命令 |
| --- | --- |
| 供应商激活码签发 GUI | `powershell -ExecutionPolicy Bypass -File tools/build_license_issuer.ps1` |
| 命令行签发 | `python tools/license_keygen.py issue --days 30 --machine local` |

---

## 八、修改构建配置时

| 需求 | 修改位置 |
| --- | --- |
| 增加数据文件/资源 | `Trading_Agent.spec` 或 `tools/build_windows_nuitka.ps1` 的 `--include-data-*` |
| 轮换 Ed25519 公钥 | `python tools/license_keygen.py generate-keys` → 自动 `sync_embedded_pubkey.py` → 重打包 |
| 缺少隐式导入的第三方库 | `Trading_Agent.spec` → `hiddenimports` |
| 程序图标 | `Trading_Agent.spec` → `EXE(..., icon='path/to.ico')` |
| 安装包版本号/名称 | `tools/installer.iss` → `#define MyAppVersion` 等 |
| 项目版本号 | `pyproject.toml` → `[project] version` |

改完后执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_windows.ps1 -Clean
```

---

## 九、Agent 执行检查表

执行任务前后可按此核对：

1. 工作目录是否为 `PA_Agent` 根目录（含 `pyproject.toml`、`Trading_Agent.spec`）
2. 运行 `tools/build_windows.ps1`，记录是否 `Build complete`
3. 确认 `dist/Trading_Agent/Trading_Agent.exe` 存在
4. 若用户要求安装包，加 `-Installer` 并确认 `dist/Trading_Agent_Setup.exe`
5. 向用户报告：版本号、exe 路径、安装包路径（如有）、是否跳过测试
6. **不要**将 `tools/.license_keys/`、`config/settings.json` 提交或发给客户
