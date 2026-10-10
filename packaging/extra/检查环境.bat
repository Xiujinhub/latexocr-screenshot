@echo off
rem 双击本文件即可自检：确认这台电脑上程序能否正常识别（首次约 10~30 秒）
chcp 65001 >nul
echo ============================================
echo   公式截图识别 —— 环境自检
echo ============================================
echo.
"%~dp0latexocr-cli.exe" --selfcheck
echo.
echo 如果上面显示 PASS，就可以正常使用了。
pause
