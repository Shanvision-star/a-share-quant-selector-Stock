"""FastAPI 应用入口"""
import sys
import logging
import os
from contextlib import asynccontextmanager
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

# 注册路由
from web.backend.routers import (
    kline,
    strategy,
    stock,
    update,
    config_api,
    backtest,
    trajectory,
    txt_export,
    manual_selection,
)


def _resolve_cors_origins() -> list:
    """从 WEB_CORS_ORIGINS 解析 CORS 白名单。

    - 为空时使用本地开发默认值（localhost / 127.0.0.1 的 5173 / 5000）。
    - 显式传入 "*" 时退化为通配，但同时关闭 allow_credentials，避免浏览器丢 cookie。
    """
    raw = os.getenv("WEB_CORS_ORIGINS", "").strip()
    if not raw:
        return [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5000",
            "http://127.0.0.1:5000",
        ]
    return [item.strip() for item in raw.split(",") if item.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI lifespan：启动时初始化数据库与预热，关闭时无需特殊清理。"""
    # 启动阶段
    try:
        init_database()
    except Exception:
        logger.exception("启动时初始化 SQLite 失败")
        raise

    try:
        stock.trigger_metric_snapshot_prewarm()
    except Exception:
        # 预热失败不阻断启动，但要保留完整 traceback 便于排查
        logger.exception("股票指标快照预热失败，将以冷启动方式提供服务")

    yield
    # 关闭阶段（暂无）


app = FastAPI(
    title="A股量化选股系统 API",
    description="量化选股系统 Web 接口",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS 配置：通过 WEB_CORS_ORIGINS 环境变量控制白名单
_cors_origins = _resolve_cors_origins()
_allow_credentials = "*" not in _cors_origins
if not _allow_credentials:
    logger.warning(
        "CORS 配置使用通配符 '*'，已自动禁用 allow_credentials 以符合浏览器安全要求"
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS 白名单: %s", _cors_origins)

app.include_router(kline.router)
app.include_router(strategy.router)
app.include_router(stock.router)
app.include_router(update.router)
app.include_router(config_api.router)
app.include_router(backtest.router)
app.include_router(trajectory.router)
app.include_router(txt_export.router)
app.include_router(manual_selection.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0"}


# 生产环境：挂载 Vue 构建产物
frontend_dist = project_root / "web" / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

