"""Codex CLI Provider。

本 provider 只负责把 Tracking LLM prompt 交给本机或服务器上的 `codex exec`，
并要求 CLI 输出严格 JSON。它用于受控 smoke，不写文件、不读取真实交易通道，
失败时由上层回退到 mock。
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
        schema_path.write_text(json.dumps(_ADVICE_SCHEMA, ensure_ascii=False), encoding="utf-8")

        args = [
            *_split_command(command),
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
        ]
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
        return _parse_json_object(content)
