"""FastAPI 应用入口"""
import sys
import logging
import os
from pathlib import Path

# 确保项目根目录在 sys.path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

# 配置日志：默认 INFO，可通过 WEB_LOG_LEVEL 覆盖。
log_level_name = os.getenv("WEB_LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_name, logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# 第三方库噪音压制
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from web.backend.services.sqlite_service import init_database

app = FastAPI(
    title="A股量化选股系统 API",
    description="量化选股系统 Web 接口",
    version="2.0.0",
)

# Initialize the database
init_database()

# CORS 配置（开发阶段允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 生产环境应限制为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from web.backend.routers import kline, strategy, stock, update, config_api, backtest, trajectory, txt_export

app.include_router(kline.router)
app.include_router(strategy.router)
app.include_router(stock.router)
app.include_router(update.router)
app.include_router(config_api.router)
app.include_router(backtest.router)
app.include_router(trajectory.router)
app.include_router(txt_export.router)


@app.on_event("startup")
async def prewarm_stock_metric_snapshot():
    try:
        stock.trigger_metric_snapshot_prewarm()
    except Exception:
        pass


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0"}


# 生产环境：挂载 Vue 构建产物
frontend_dist = project_root / "web" / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
