@echo off
rem 命令行版公式识别。用法示例： run_cli.bat --selfcheck
chcp 65001 >nul
setlocal
set "PY=D:\Anaconda\envs\OCR\python.exe"
if not exist "%PY%" set "PY=python"
set PYTHONIOENCODING=utf-8
"%PY%" "%~dp0latex_ocr_cli.py" %*
endlocal
