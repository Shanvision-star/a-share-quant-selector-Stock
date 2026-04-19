@echo off
chcp 65001 >nul
title A-Share Quant Dev Server

cd /d "%~dp0"

echo [1/2] 启动后端 FastAPI (port 8001)...
start "后端 API" cmd /k ".venv\Scripts\uvicorn.exe web.backend.main:app --host 0.0.0.0 --port 8001 --reload"

timeout /t 2 >nul

echo [2/2] 启动前端 Vite (port 5173)...
start "前端 Vite" cmd /k "cd web\frontend && npm run dev"

echo.
echo 后端: http://localhost:8001/api/health
echo 前端: http://localhost:5173
echo.
echo 两个窗口已分别打开，关闭对应窗口即可停止服务。
pause
