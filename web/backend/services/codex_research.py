"""桌面 Codex 研究入口：复用登录态、封闭证据包和可追溯策略实现快照。"""

from __future__ import annotations

import hashlib
import inspect
import os
from pathlib import Path
import shutil
import tomllib

from .llm_providers.codex_cli_provider import call_codex_cli, CodexCLIError
from .llm_providers.llm_config import load_llm_config


def codex_settings() -> dict:
    """只读取模型名称；不把用户全局配置、MCP 配置或凭据传进研究上下文。"""
    configured = load_llm_config().get('codex_cli') or {}
    command = configured.get('command')
    if not command:
        candidates = [os.environ.get('CODEX_CLI_PATH')]
        if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
            binary_dir = Path(os.environ['LOCALAPPDATA']) / 'OpenAI/Codex/bin'
            # 应用更新后的版本目录优先；PATH 中的旧启动器可能不能连接当前模型。
            installed = sorted(binary_dir.glob('*/codex.exe'), key=lambda path: path.stat().st_mtime, reverse=True)
            candidates.extend(str(path) for path in installed)
            candidates.append(str(binary_dir / 'codex.exe'))
        candidates.append(shutil.which('codex'))
        command = next((value for value in candidates if value and Path(value).is_file()), None)
    model = configured.get('model')
    if not model:
        try:
            profile = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'config.toml'
            model = tomllib.loads(profile.read_text(encoding='utf-8')).get('model')
        except (OSError, ValueError):
            pass
    available = bool(command and (Path(command).is_file() or shutil.which(command)))
    return {'command': command, 'available': available, 'model': model}


def call_codex_research(system: str, user: str, schema: dict) -> tuple[str, dict]:
    settings = codex_settings()
    if not settings['available']:
        raise ValueError('未找到 Codex CLI，请安装并登录 Codex 后重试')
    prompt = (system + '\n这是封闭证据分析任务。仅使用下方 JSON，不调用工具，不读写文件，不执行交易。'
              '逐项解释策略条件、指标是否支持、反证和待观察条件。区分历史信号与当前实现；'
              '来源 run_status 非 completed 时明确提醒扫描未成功，不能宣称已重新验证信号。'
              '没有实际重跑或回测证据时，不声称完成重算、胜率或收益验证。\n证据 JSON：\n' + user)
    try:
        result = call_codex_cli(command=settings['command'], model=settings['model'], prompt=prompt,
                                output_schema=schema, research_only=True, timeout_seconds=180)
    except CodexCLIError as exc:
        raise ValueError(f'{exc}；请检查本机 Codex 登录、网络和可用额度；未回退为模拟报告') from exc
    return result['content'], {'provider': 'codex_cli', 'model': settings['model'] or 'Codex 默认模型（标识未返回）',
                               'usage': result['usage'], 'cost': None, 'codex_tool_calls': result['tool_calls']}


def strategy_implementation_snapshot(root: Path, records: list[dict]) -> dict:
    """补充已命中策略的当前参数和实现；明确它不是历史配置还原，也不触发扫描。"""
    from .strategy_service import get_resolved_strategy_items
    names = list(dict.fromkeys(row.get('strategy_name') for row in records if row.get('strategy_name')))
    if not names:
        return {'total': 0, 'items': []}
    _, resolved = get_resolved_strategy_items()
    strategies = {name: strategy for _, name, strategy in resolved}
    items = []
    remaining = 32000
    for name in names[:5]:
        strategy = strategies.get(name)
        if strategy is None:
            items.append({'strategy_name': name, 'unavailable': '当前注册表无此策略'})
            continue
        path = Path(inspect.getfile(type(strategy))).resolve()
        if not path.is_relative_to((root / 'strategy').resolve()):
            items.append({'strategy_name': name, 'unavailable': '策略实现不在正式策略目录'})
            continue
        raw = path.read_bytes()
        content = raw.decode('utf-8-sig')
        excerpt = content[:min(16000, remaining)]
        remaining -= len(excerpt)
        items.append({'strategy_name': name, 'current_params': strategy.params,
                      'module': path.relative_to(root).as_posix(), 'file_sha256': hashlib.sha256(raw).hexdigest(),
                      'implementation': excerpt, 'code_truncated': len(excerpt) < len(content)})
    return {'total': len(names), 'items': items, 'limit': 5,
            'scope': '当前策略参数和源码片段，未重跑策略；历史运行参数和依赖函数未完整还原。'}
