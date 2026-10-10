@echo off
rem 发布 Release 并上传安装包。用法：
rem   packaging\publish_release.bat v1.0.1
rem 前置：装好 GitHub CLI 并已 gh auth login；先跑过 packaging\build_installer.bat
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
set "VER=%~1"
if "%VER%"=="" set "VER=v1.0.0"
set "VERNUM=%VER:v=%"
set "ASSET=dist\LaTeXOCR-Setup-%VERNUM%.exe"
set "GH=%ProgramFiles%\GitHub CLI\gh.exe"
if not exist "%GH%" set "GH=gh"

if not exist "%ASSET%" (
  echo [x] not found: %ASSET%
  echo     run packaging\build_installer.bat first.
  exit /b 1
)

echo [1/2] creating release %VER% and uploading %ASSET% ...
"%GH%" release create %VER% "%ASSET%" --title "%VER%" --notes-file CHANGELOG.md
if errorlevel 1 (
  echo [x] release create failed. If the tag already exists, upload the asset instead:
  echo     "%GH%" release upload %VER% "%ASSET%" --clobber
  exit /b 1
)

echo [2/2] done:
"%GH%" release view %VER%
endlocal
