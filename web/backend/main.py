"""FastAPI 应用入口"""
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="A股量化选股系统 API",
    description="量化选股系统 Web 接口",
    version="2.0.0",
)

# CORS 配置（开发阶段允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 生产环境应限制为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from web.backend.routers import kline, strategy, stock, update, config_api, backtest

app.include_router(kline.router)
app.include_router(strategy.router)
app.include_router(stock.router)
app.include_router(update.router)
app.include_router(config_api.router)
app.include_router(backtest.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0"}


# 生产环境：挂载 Vue 构建产物
frontend_dist = project_root / "web" / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
