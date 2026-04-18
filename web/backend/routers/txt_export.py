"""TDX（通达信）TXT 文件导出接口"""
import re
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api", tags=["TXT导出"])

TXT_WEB_DIR = Path(__file__).resolve().parents[3] / "data" / "txt" / "web_export"
_SAFE_NAME = re.compile(r'^[\w\-\.]+\.txt$')


def _get_txt_dir() -> Path:
    TXT_WEB_DIR.mkdir(parents=True, exist_ok=True)
    return TXT_WEB_DIR


@router.get('/txt/info')
async def get_txt_info():
    """返回 TXT 文件导出目录信息"""
    txt_dir = _get_txt_dir()
    project_root = Path(__file__).resolve().parents[3]
    try:
        relative_dir = str(txt_dir.relative_to(project_root)).replace('\\', '/')
    except Exception:
        relative_dir = str(txt_dir).replace('\\', '/')

    return {
        'success': True,
        'data': {
            'storage_dir': str(txt_dir),
            'relative_dir': relative_dir,
            'filename_pattern': 'tdx_web_{strategy}_{yyyymmdd}.txt',
        },
    }


def _code_to_tdx(code: str) -> str:
    """将股票代码转换为通达信格式，如 SH600000 / SZ000001 / BJ430047"""
    if code.startswith("6"):
        return f"SH{code}"
    elif code.startswith(("8", "4")):
        return f"BJ{code}"
    else:
        return f"SZ{code}"


STRATEGY_LABEL = {
    "all": "全部",
    "b1": "B1形态",
    "b2": "B2突破",
    "bowl": "碗底反弹",
}


@router.get("/txt/files")
async def list_txt_files(date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """列出 TXT 文件库（按日期过滤）"""
    txt_dir = _get_txt_dir()
    files = []
    for f in sorted(txt_dir.glob("tdx_web_*.txt"), reverse=True):
        stat = f.stat()
        # 格式：tdx_web_{strategy}_{date8}.txt
        parts = f.stem.split("_")
        if len(parts) >= 4:
            strategy = parts[2]
            file_date8 = parts[3]  # YYYYMMDD
            file_date = f"{file_date8[:4]}-{file_date8[4:6]}-{file_date8[6:]}" if len(file_date8) == 8 else file_date8
        else:
            strategy = "unknown"
            file_date = "unknown"
            file_date8 = "unknown"

        if date and file_date != date:
            continue

        # 统计行数（股票数量）
        try:
            count = sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
        except Exception:
            count = 0

        files.append({
            "filename": f.name,
            "strategy": strategy,
            "strategy_label": STRATEGY_LABEL.get(strategy, strategy),
            "date": file_date,
            "count": count,
            "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return {"success": True, "data": files}


@router.get("/txt/dates")
async def list_txt_dates():
    """列出 TXT 文件库中已有的日期列表"""
    txt_dir = _get_txt_dir()
    date_set = set()
    for f in txt_dir.glob("tdx_web_*.txt"):
        parts = f.stem.split("_")
        if len(parts) >= 4:
            d8 = parts[3]
            if len(d8) == 8:
                date_set.add(f"{d8[:4]}-{d8[4:6]}-{d8[6:]}")
    dates = sorted(date_set, reverse=True)
    return {"success": True, "data": dates}


@router.post("/txt/generate")
async def generate_txt_file(
    strategy: str = Query("all", pattern="^(all|b1|b2|bowl)$"),
    date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """从策略结果数据库生成通达信 TXT 文件"""
    from web.backend.services import strategy_result_repository as repo

    if not date:
        dates = repo.get_available_trade_dates(1)
        if not dates:
            return {"success": False, "error": "暂无策略结果数据，请先执行选股"}
        date = dates[0]

    # 查询统计摘要（信号条数 + 去重股票数）
    summary = repo.query_results(
        strategy_filter=strategy,
        start_date=date,
        end_date=date,
        page=1,
        per_page=1,
    )
    total_signals = int(summary.get("total", 0))
    unique_code_total = int(summary.get("unique_code_total", 0))

    if total_signals <= 0:
        return {"success": False, "error": f"日期 {date} 暂无「{STRATEGY_LABEL.get(strategy, strategy)}」选股结果"}

    # 直接查询去重后的完整代码列表，避免分页截断导致漏导出。
    codes = repo.query_unique_codes(
        strategy_filter=strategy,
        start_date=date,
        end_date=date,
    )
    lines = [_code_to_tdx(str(code).strip()) for code in codes if str(code).strip()]

    date8 = date.replace("-", "")
    filename = f"tdx_web_{strategy}_{date8}.txt"
    filepath = _get_txt_dir() / filename

    filepath.write_text("\n".join(lines), encoding="utf-8")

    return {
        "success": True,
        "data": {
            "filename": filename,
            "count": len(lines),
            "unique_code_total": unique_code_total,
            "signal_total": total_signals,
            "overlap_signal_count": max(0, total_signals - len(lines)),
            "date": date,
            "strategy": strategy,
            "strategy_label": STRATEGY_LABEL.get(strategy, strategy),
        },
    }


@router.get("/txt/download/{filename}")
async def download_txt_file(filename: str):
    """下载 TXT 文件"""
    # 安全校验：防止路径穿越
    if not _SAFE_NAME.match(filename):
        raise HTTPException(status_code=400, detail="非法文件名")

    filepath = _get_txt_dir() / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
