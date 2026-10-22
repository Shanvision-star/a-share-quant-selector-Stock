@echo off
setlocal
cd /d "%~dp0"
set "QUANT_WORKSPACE=%~dp0"
if exist "desktop\release\A-share-Quant-0.1.0.exe" (
  start "" "desktop\release\A-share-Quant-0.1.0.exe"
) else (
  call npm --prefix desktop start
)
