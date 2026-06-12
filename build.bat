@echo off
REM One-click Windows build wrapper. See docs\构建EXE.md
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_windows.ps1" %*
