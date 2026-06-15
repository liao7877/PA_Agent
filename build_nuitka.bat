@echo off
REM Nuitka release build. See docs\构建EXE.md
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_windows_nuitka.ps1" %*
