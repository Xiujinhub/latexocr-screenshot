@echo off
rem 启动公式截图识别工具（GUI）。如 conda 环境路径不同，改下面的 PY 即可。
chcp 65001 >nul
setlocal
set "PY=D:\Anaconda\envs\OCR\pythonw.exe"
if not exist "%PY%" set "PY=D:\Anaconda\envs\OCR\python.exe"
if not exist "%PY%" set "PY=pythonw"
start "" "%PY%" "%~dp0screenshot_latex.py" %*
endlocal
