# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PA Agent License Issuer GUI (vendor tool)."""

from pathlib import Path

root = Path(SPECPATH)

# Vendor issuer must never bundle the private key.
_private_key = root / "tools" / ".license_keys" / "license_private.pem"
if _private_key.is_file():
    print("WARNING: private key exists locally but will NOT be packaged into the issuer exe.")

datas = [
    (str(root / "pa_agent" / "licensing" / "public_key.pem"), "pa_agent/licensing"),
]

hiddenimports = [
    "pa_agent.licensing.issuer",
    "pa_agent.licensing.crypto",
    "pa_agent.licensing.validator",
    "pa_agent.licensing.machine_id",
]

a = Analysis(
    [str(root / "tools" / "license_issuer_gui.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "hypothesis",
        "black",
        "ruff",
        "MetaTrader5",
        "pandas",
        "numpy",
        "openai",
        "pyqtgraph",
        "tvDatafeed",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PA_Agent_License_Issuer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    onefile=True,
)
