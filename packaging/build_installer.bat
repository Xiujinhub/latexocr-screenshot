@echo off
rem 一键打包：PyInstaller 生成 dist\LaTeXOCR（含模型权重），再用 Inno Setup 生成安装包。
rem 用法：双击本文件，或在仓库根目录执行 packaging\build_installer.bat
setlocal
chcp 65001 >nul
set "PY=D:\Anaconda\envs\OCR\python.exe"
if not exist "%PY%" set "PY=python"
set "ROOT=%~dp0.."
cd /d "%ROOT%"

echo [1/5] 生成图标 …
"%PY%" packaging\make_icon.py || goto :fail

echo.
echo [2/5] PyInstaller 打包（第一次较慢，几分钟）…
"%PY%" -m PyInstaller packaging\latexocr.spec --noconfirm --clean || goto :fail

echo.
echo [3/5] 自检打包结果（真跑一遍识别）…
dist\LaTeXOCR\latexocr-cli.exe --selfcheck || goto :fail

echo.
echo [4/5] 查找 Inno Setup 编译器 …
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo   没找到 ISCC.exe。请先装 Inno Setup 6：
  echo     winget install --id JRSoftware.InnoSetup -e
  echo   绿色免安装版也已经生成好了：dist\LaTeXOCR\LaTeXOCR.exe
  goto :fail
)

echo.
echo [5/5] 生成安装包 …
"%ISCC%" /Qp packaging\installer.iss || goto :fail

echo.
echo ============================================================
echo  打包完成：
echo    免安装目录 : %ROOT%\dist\LaTeXOCR\LaTeXOCR.exe
echo    安装包     : %ROOT%\dist\LaTeXOCR-Setup-1.0.0.exe
echo ============================================================
exit /b 0

:fail
echo.
echo *** 打包未完成，请查看上面的输出 ***
exit /b 1
