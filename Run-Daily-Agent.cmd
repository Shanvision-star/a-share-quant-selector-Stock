@echo off
setlocal
set "PYTHONIOENCODING=utf-8"
set "QUANT_DAILY_PYTHON=%LOCALAPPDATA%\Programs\A-share Quant\resources\python\python.exe"
if not exist "%QUANT_DAILY_PYTHON%" (
  echo Windows desktop runtime was not found. Install A-share Quant first.
  exit /b 1
)
"%QUANT_DAILY_PYTHON%" "%~dp0scripts\run_daily_agent.py" %*
exit /b %errorlevel%
