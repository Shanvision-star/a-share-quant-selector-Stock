@echo off
chcp 65001 >nul
title A-Share Quant Dev Server

cd /d "%~dp0"

echo [0/2] 检查前后端版本与端口...
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\dev_preflight.py" --project-root "%~dp0" --ports 8001 5173
if errorlevel 1 (
    echo.
    echo 启动已停止。请按上面的提示关闭旧服务或同步前端子仓。
    pause
    exit /b 1
)

echo [1/2] 启动后端 FastAPI (port 8001)...
start "后端 API" /d "%~dp0" cmd /k ""%~dp0.venv\Scripts\python.exe" "%~dp0scripts\run_web_backend.py" --host 127.0.0.1 --port 8001"

powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 20;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8001/api/health' -TimeoutSec 2; if($r.StatusCode -eq 200){$ok=$true; break} } catch {}; Start-Sleep -Milliseconds 500 }; if(-not $ok){exit 1}"
if errorlevel 1 (
    echo 后端健康检查失败，请查看“后端 API”窗口。
    pause
    exit /b 1
)

echo [2/2] 启动前端 Vite (port 5173)...
start "前端 Vite" /d "%~dp0web\frontend" cmd /k "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort"

powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 20;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173/' -TimeoutSec 2; if($r.StatusCode -eq 200){$ok=$true; break} } catch {}; Start-Sleep -Milliseconds 500 }; if(-not $ok){exit 1}"
if errorlevel 1 (
    echo 前端健康检查失败，请查看“前端 Vite”窗口。
    pause
    exit /b 1
)

echo.
echo 后端: http://localhost:8001/api/health
echo 前端: http://localhost:5173
echo.
echo 两个服务均已通过健康检查。关闭对应窗口即可停止服务。
pause
