"""LLM provider 适配层。

提供统一入口：根据 config/llm.yaml 中的 provider 字段，分派到
具体 provider（目前实现 deepseek / codex_cli，预留 mock 作为兜底）。
"""

from .codex_cli_provider import CodexCLIError, call_codex_cli
from .deepseek_provider import call_deepseek
from .llm_config import load_llm_config

__all__ = ["CodexCLIError", "call_codex_cli", "call_deepseek", "load_llm_config"]
