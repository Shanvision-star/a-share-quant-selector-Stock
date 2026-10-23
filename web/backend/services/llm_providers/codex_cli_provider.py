"""Codex CLI Provider。

复用本机或服务器上的 `codex exec`，支持原 Tracking LLM 与桌面研究 JSON 协议。
研究模式使用临时工作目录，关闭 Shell、插件、应用与多 Agent 工具，保留真实用量。
失败统一抛异常；桌面研究记录失败，原 Tracking LLM 继续按自身边界处理回退。
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class CodexCLIError(RuntimeError):
    """Codex CLI 调用失败统一异常，便于上层兜底。"""


_ADVICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "decision",
        "confidence",
        "rationale",
        "suggested_action",
        "suggested_intent",
        "analysis",
    ],
    "properties": {
        "decision": {"type": "string", "enum": ["cut", "reduce", "hold", "watch", "add"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "suggested_action": {"type": "string", "enum": ["SELL", "REDUCE", "HOLD", "WAIT", "BUY"]},
        "suggested_intent": {
            "type": "object",
            "required": ["code", "side", "qty_hint", "reason"],
            "properties": {
                "code": {"type": "string"},
                "side": {"type": "string"},
                "qty_hint": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "analysis": {
            "type": "object",
            "required": ["technical", "discipline", "risk", "next_step"],
            "properties": {
                "technical": {"type": "array", "items": {"type": "string"}},
                "discipline": {"type": "array", "items": {"type": "string"}},
                "risk": {"type": "array", "items": {"type": "string"}},
                "next_step": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


def _split_command(command: str) -> list[str]:
    """把配置中的 CLI 命令拆成 subprocess 参数，避免 shell=True。"""
    value = str(command or "").strip()
    if not value:
        raise CodexCLIError("Codex CLI command 未配置")
    if Path(value).exists():
        return [value]
    try:
        parts = shlex.split(value, posix=os.name != "nt")
    except ValueError as exc:
        raise CodexCLIError("Codex CLI command 解析失败") from exc
    cleaned = [part.strip('"') for part in parts if part.strip()]
    if not cleaned:
        raise CodexCLIError("Codex CLI command 未配置")
    return cleaned


def _parse_json_object(text: str) -> dict[str, Any]:
    """解析 CLI 输出；允许外层误带 ```json 围栏，但顶层必须是对象。"""
    content = str(text or "").strip()
    if not content:
        raise CodexCLIError("Codex CLI 未返回内容")
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise CodexCLIError("Codex CLI 返回内容非 JSON 对象") from None
        try:
            parsed = json.loads(content[start : end + 1])
        except json.JSONDecodeError as exc:
            raise CodexCLIError("Codex CLI 返回内容非 JSON 对象") from exc

    if not isinstance(parsed, dict):
        raise CodexCLIError(f"Codex CLI 返回顶层非对象: {type(parsed).__name__}")
    return parsed


def call_codex_cli(
    *,
    command: str,
    prompt: str,
    model: str | None = None,
    cwd: str | None = None,
    timeout_seconds: float = 60.0,
    output_schema: dict[str, Any] | None = None,
    research_only: bool = False,
) -> dict[str, Any]:
    """调用 `codex exec` 并返回解析后的 JSON 字典。

    Raises:
        CodexCLIError: CLI 不存在、超时、非零退出或输出非 JSON 时抛出。
    """
    if not str(prompt or "").strip():
        raise CodexCLIError("Codex CLI prompt 为空")

    with tempfile.TemporaryDirectory(prefix="codex-cli-provider-") as tmp:
        temp_dir = Path(tmp)
        schema_path = temp_dir / "tracking_advice.schema.json"
        output_path = temp_dir / "tracking_advice.json"
        schema_path.write_text(json.dumps(output_schema or _ADVICE_SCHEMA, ensure_ascii=False), encoding="utf-8")

        args = [
            *_split_command(command),
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
        ]
        if research_only:
            # 研究只接收证据包，不给模型工作区、Shell、联网搜索或全局 MCP 工具。
            args.extend(["--json", "--skip-git-repo-check", "--disable", "shell_tool",
                         "--disable", "plugins", "--disable", "apps", "--disable", "multi_agent",
                         "-c", 'web_search="disabled"', "-c", 'approval_policy="never"'])
            cwd = str(temp_dir)
        if model:
            args.extend(["--model", str(model)])
        if cwd:
            args.extend(["--cd", str(cwd)])
        args.extend(
            [
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ]
        )

        try:
            completed = subprocess.run(
                args,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_seconds,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError as exc:
            raise CodexCLIError("Codex CLI 命令未找到") from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexCLIError(f"Codex CLI 超时 {timeout_seconds:g} 秒") from exc
        except OSError as exc:
            raise CodexCLIError(f"Codex CLI 启动失败: {type(exc).__name__}") from exc

        if completed.returncode != 0:
            raise CodexCLIError(f"Codex CLI 退出码 {completed.returncode}")

        if output_path.exists():
            content = output_path.read_text(encoding="utf-8")
        else:
            content = completed.stdout
        if research_only:
            usage = None
            tool_calls = []
            for line in completed.stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                item_type = (event.get('item') or {}).get('type')
                if event.get('type') == 'item.completed' and item_type in ('command_execution', 'mcp_tool_call', 'web_search', 'file_change', 'dynamic_tool_call'):
                    tool_calls.append(item_type)
            if usage:
                usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            # 把原始正文交给上层校验，格式错误时仍可记录已发生的模型用量。
            return {"content": content, "usage": usage, "tool_calls": tool_calls}
        return _parse_json_object(content)
