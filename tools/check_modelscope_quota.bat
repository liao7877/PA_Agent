@echo off
setlocal
cd /d "%~dp0.."
python tools\check_modelscope_quota.py %*
