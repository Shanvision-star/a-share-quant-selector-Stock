"""Codex CLI provider 的本地编排测试。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_call_codex_cli_uses_read_only_exec_and_parses_json(monkeypatch, tmp_path) -> None:
    """provider 应用只读 exec 调 Codex CLI，并解析 last-message JSON。"""
    from web.backend.services.llm_providers.codex_cli_provider import call_codex_cli

    seen: dict[str, object] = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        output_path = Path(args[args.index("--output-last-message") + 1])
        schema_path = Path(args[args.index("--output-schema") + 1])
        assert schema_path.exists()
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        assert "analysis" in schema["required"]
        assert schema["properties"]["suggested_intent"]["additionalProperties"] is False
        assert schema["properties"]["analysis"]["required"] == [
            "technical",
            "discipline",
            "risk",
            "next_step",
        ]
        output_path.write_text(
            json.dumps(
                {
                    "decision": "hold",
                    "confidence": 0.72,
                    "rationale": "继续观察。",
                    "suggested_action": "HOLD",
                    "suggested_intent": {
                        "code": "000001",
                        "side": "HOLD",
                        "qty_hint": 100,
                        "reason": "cli_smoke",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    raw = call_codex_cli(
        command="codex",
        model="gpt-test",
        prompt="只输出 JSON",
        cwd=str(tmp_path),
        timeout_seconds=12,
    )

    args = seen["args"]
    assert args[:2] == ["codex", "exec"]
    assert "--ephemeral" in args
    assert "--ignore-user-config" in args
    assert "--ignore-rules" not in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("--model") + 1] == "gpt-test"
    assert args[args.index("--cd") + 1] == str(tmp_path)
    assert args[-1] == "-"
    assert seen["kwargs"]["input"] == "只输出 JSON"
    assert seen["kwargs"]["timeout"] == 12
    assert raw["decision"] == "hold"


def test_call_codex_cli_nonzero_raises_sanitized_error(monkeypatch) -> None:
    """CLI 非零退出时抛统一异常，不把完整 stderr 透给上层。"""
    from web.backend.services.llm_providers.codex_cli_provider import (
        CodexCLIError,
        call_codex_cli,
    )

    def fake_run(_args, **_kwargs):
        return SimpleNamespace(returncode=7, stdout="token-like-output", stderr="very secret detail")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(CodexCLIError, match="退出码 7"):
        call_codex_cli(command="codex", prompt="只输出 JSON", timeout_seconds=1)


def test_research_is_sealed_and_keeps_usage_for_invalid_report(monkeypatch):
    """研究隔离 Shell 与项目目录；输出无效也保留计量供运行审计。"""
    from web.backend.services.llm_providers.codex_cli_provider import call_codex_cli
    schema = {'type': 'object', 'properties': {'summary': {'type': 'string'}}, 'required': ['summary'], 'additionalProperties': False}
    def fake_run(args, **kwargs):
        assert '--json' in args and '--skip-git-repo-check' in args
        assert args[args.index('--disable') + 1] == 'shell_tool'
        assert {'plugins', 'apps', 'multi_agent'} <= set(args)
        assert args[args.index('--cd') + 1] != 'real-workspace'
        assert 'web_search="disabled"' in args and 'approval_policy="never"' in args
        assert '--ignore-rules' not in args
        assert json.loads(Path(args[args.index('--output-schema') + 1]).read_text()) == schema
        Path(args[args.index('--output-last-message') + 1]).write_text('invalid report')
        return SimpleNamespace(returncode=0, stdout=json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 15}}))
    monkeypatch.setattr(subprocess, 'run', fake_run)
    result = call_codex_cli(command='codex', prompt='evidence', cwd='real-workspace', research_only=True, output_schema=schema)
    assert result['content'] == 'invalid report'
    assert result['usage']['total_tokens'] == 115
    assert result['tool_calls'] == []
