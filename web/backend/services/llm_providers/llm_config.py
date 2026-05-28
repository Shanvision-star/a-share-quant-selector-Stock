"""读取 LLM 配置文件。

设计要点：
- 优先读取 config/llm.yaml（gitignored，存放真实密钥）；
- 文件缺失或解析失败时回退到 {"provider": "mock"}，保证离线/CI 不报错；
- 缓存通过文件 mtime 失效，避免修改配置后需要重启服务。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

# web/backend/services/llm_providers/llm_config.py → parents[4] = 仓库根
_project_root = Path(__file__).resolve().parents[4]
_LLM_CONFIG_FILE = _project_root / "config" / "llm.yaml"
_LOCK = threading.RLock()

_cache: dict[str, Any] | None = None
_cache_mtime: float | None = None


def _default_config() -> dict[str, Any]:
    """缺失/失败时回退的最小配置：等同于纯 mock。"""
    return {"provider": "mock"}


def load_llm_config(force_reload: bool = False) -> dict[str, Any]:
    """加载 LLM 配置；线程安全 + mtime 失效。"""
    global _cache, _cache_mtime

    with _LOCK:
        if not _LLM_CONFIG_FILE.exists():
            # 关键路径：未配置文件时不要抛错，回到 mock
            _cache = _default_config()
            _cache_mtime = None
            return dict(_cache)

        mtime = _LLM_CONFIG_FILE.stat().st_mtime
        if (
            not force_reload
            and _cache is not None
            and _cache_mtime is not None
            and mtime == _cache_mtime
        ):
            return dict(_cache)

        try:
            with open(_LLM_CONFIG_FILE, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            if not isinstance(raw, dict):
                raw = _default_config()
        except Exception:
            # 解析错误降级到 mock，避免影响线上跟踪流程
            raw = _default_config()

        # 强约束 provider 字段
        raw.setdefault("provider", "mock")
        _cache = raw
        _cache_mtime = mtime
        return dict(_cache)
