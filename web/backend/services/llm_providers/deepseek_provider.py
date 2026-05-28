"""DeepSeek（OpenAI 兼容）Provider。

设计要点：
- 仅依赖 httpx；不引入额外 SDK，方便测试 monkeypatch；
- 强制 response_format=json_object，结合系统提示要求严格 JSON 输出；
- 任何网络/解析异常向上抛出，由上层 tracking_llm_service 捕获并回退 mock。
"""

from __future__ import annotations

import json
from typing import Any

import httpx


class DeepSeekError(RuntimeError):
    """DeepSeek 调用失败统一异常，便于上层兜底。"""


def call_deepseek(
    *,
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    timeout_seconds: float = 20.0,
    max_output_tokens: int = 600,
) -> dict[str, Any]:
    """调用 DeepSeek /chat/completions，返回解析后的 JSON 字典。

    Raises:
        DeepSeekError: 网络异常、HTTP 非 2xx、内容非 JSON 时抛出。
    """
    if not api_key:
        raise DeepSeekError("DeepSeek api_key 未配置")

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_output_tokens,
        # DeepSeek 支持 OpenAI 风格的 json_object 强约束输出
        "response_format": {"type": "json_object"},
    }

    try:
        # 关键路径：单次同步调用，超时由调用方传入；不开重试，避免阻塞跟踪评估
        resp = httpx.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        raise DeepSeekError(f"DeepSeek 请求失败: {exc}") from exc

    if resp.status_code >= 400:
        raise DeepSeekError(
            f"DeepSeek HTTP {resp.status_code}: {resp.text[:200]}"
        )

    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise DeepSeekError(f"DeepSeek 响应结构异常: {exc}") from exc

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise DeepSeekError(f"DeepSeek 返回内容非 JSON: {content[:200]}") from exc

    if not isinstance(parsed, dict):
        raise DeepSeekError(f"DeepSeek 返回顶层非对象: {type(parsed).__name__}")

    return parsed
