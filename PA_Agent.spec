# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PA Agent Windows distribution."""

import sys
from pathlib import Path

root = Path(SPECPATH)

_license_client = root / "config" / "license_client.json"
if not _license_client.is_file():
    _license_client = root / "config" / "license_client.example.json"

# Never bundle developer settings.json, records, logs, or private keys.
datas = [
    (str(root / "prompt_engineering"), "prompt_engineering"),
    (str(root / "config" / "settings.example.json"), "config"),
    (str(_license_client), "config"),
    (str(root / "pa_agent" / "gui" / "theme" / "dark.qss"), "pa_agent/gui/theme"),
]

for _src, _dst in datas:
    _name = Path(_src).name.lower()
    if _name in {"settings.json", "license_private.pem"} or _name.endswith(".key"):
        raise SystemExit(f"Refusing to bundle forbidden file: {_src}")

hiddenimports = [
    "MetaTrader5",
    "win32crypt",
    "pywintypes",
    "tiktoken_ext.openai_public",
    "tiktoken_ext",
]

a = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "hypothesis", "black", "ruff"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PA_Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PA_Agent",
)
