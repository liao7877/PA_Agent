@echo off
chcp 65001 >nul 2>&1
title PA Agent - AI K线分析助手
cd /d "%~dp0"
python run.py
if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出，请查看上方错误信息。
    pause
)