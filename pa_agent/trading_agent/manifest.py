"""Merge policy path lists — keep in sync with docs/上游合并策略.md."""

from __future__ import annotations

# Always keep our version when merging upstream/main into main.
MERGE_OURS_GLOBS: tuple[str, ...] = (
    "pa_agent/trading_agent/**",
    "pa_agent/licensing/**",
    "pa_agent/notification/**",
    "pa_agent/positions/**",
    "pa_agent/config/tracking_schedule.py",
    "pa_agent/util/local_tz.py",
    "pa_agent/ai/api_health.py",
    "build.bat",
    "build_nuitka.bat",
    "Trading_Agent.spec",
    "LicenseIssuer.spec",
    "tools/build_*.ps1",
    "tools/installer.iss",
    "tools/license_*.py",
    "tools/license_server/**",
    "tools/sync_embedded_pubkey.py",
    "tools/verify_build_safe.ps1",
    "docs/打包与授权.md",
    "docs/构建EXE.md",
    "docs/配置指南.md",
    "docs/使用指南.md",
    "docs/项目交接文档.md",
    "docs/详细规格说明书.md",
    "docs/文件索引.md",
    "docs/上游合并策略.md",
    "docs/Trading-Agent开发与上游合并操作手册.md",
    ".kiro/specs/trading-agent/**",
    "config/license_client.example.json",
    "scripts/merge-upstream.ps1",
)

# Prefer upstream when both sides changed.
MERGE_THEIRS_GLOBS: tuple[str, ...] = (
    "prompt_engineering/**",
)

# Expect manual conflict resolution each merge.
MERGE_MANUAL_GLOBS: tuple[str, ...] = (
    "pa_agent/gui/main_window.py",
    "pa_agent/orchestrator/two_stage.py",
    "pa_agent/ai/deepseek_client.py",
    "pa_agent/config/settings.py",
    "pa_agent/ai/json_validator.py",
    "pa_agent/app_context.py",
    "pa_agent/gui/settings_dialog.py",
    "pa_agent/data/factory.py",
    "pa_agent/data/mt5.py",
)
