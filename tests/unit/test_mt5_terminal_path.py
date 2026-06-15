"""Unit tests for MT5 terminal path resolution."""
from __future__ import annotations

from pathlib import Path

from pa_agent.data.mt5 import resolve_mt5_terminal_executable


def test_empty_path_returns_none() -> None:
    assert resolve_mt5_terminal_executable("") is None
    assert resolve_mt5_terminal_executable("   ") is None


def test_directory_appends_terminal64(tmp_path: Path) -> None:
    exe = tmp_path / "terminal64.exe"
    exe.write_bytes(b"")
    assert resolve_mt5_terminal_executable(str(tmp_path)) == str(exe.resolve())


def test_exe_file_passthrough(tmp_path: Path) -> None:
    exe = tmp_path / "terminal64.exe"
    exe.write_bytes(b"")
    assert resolve_mt5_terminal_executable(str(exe)) == str(exe.resolve())
