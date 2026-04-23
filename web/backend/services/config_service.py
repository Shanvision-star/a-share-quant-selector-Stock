"""策略配置文件读写服务。"""
import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path

import yaml

project_root = Path(__file__).resolve().parents[3]
CONFIG_FILE = project_root / "config" / "strategy_params.yaml"
_CONFIG_LOCK = threading.RLock()


def _load_raw_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _revision_of(config: dict) -> str:
    raw = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _updated_at() -> str:
    return datetime.fromtimestamp(CONFIG_FILE.stat().st_mtime).isoformat()


def get_config_with_revision() -> tuple[dict, str, str]:
    with _CONFIG_LOCK:
        config = _load_raw_config()
        return config, _revision_of(config), _updated_at()


def save_config(config: dict) -> str:
    with _CONFIG_LOCK:
        temp_file = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.tmp")
        with open(temp_file, "w", encoding="utf-8") as file:
            yaml.safe_dump(config, file, allow_unicode=True, default_flow_style=False, sort_keys=False)
            file.flush()
            os.fsync(file.fileno())
        temp_file.replace(CONFIG_FILE)
        return _revision_of(config)


def update_config_with_revision(
    strategy_name: str,
    new_params: dict,
    expected_revision: str,
) -> tuple[bool, str]:
    with _CONFIG_LOCK:
        config = _load_raw_config()
        current_revision = _revision_of(config)
        if expected_revision != current_revision:
            return False, current_revision

        config.setdefault(strategy_name, {}).update(new_params)
        return True, save_config(config)
