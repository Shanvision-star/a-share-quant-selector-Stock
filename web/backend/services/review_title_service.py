"""复盘标题候选服务，复用 DeepSeek 配置并始终提供本地回退。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from .llm_providers import call_deepseek, load_llm_config
from .review_repository import ReviewDocument


@dataclass(frozen=True)
class TitleSuggestion:
    """标题候选及其 provider 回退状态。"""

    title: str
    source: Literal["deepseek", "local_fallback"]
    provider_fallback: bool
    provider_error: str | None


class ReviewTitleService:
    """只生成标题候选，不负责修改或保存复盘文档。"""

    def generate(self, document: ReviewDocument) -> TitleSuggestion:
        """优先调用配置的 DeepSeek，所有异常均回退到本地候选。"""
        try:
            config = load_llm_config()
            if str(config.get("provider") or "").lower() != "deepseek":
                raise RuntimeError("DeepSeek 未配置")
            deepseek = config.get("deepseek") or {}
            raw = call_deepseek(
                api_key=str(deepseek.get("api_key") or ""),
                base_url=str(deepseek.get("base_url") or "https://api.deepseek.com/v1"),
                model=str(deepseek.get("model") or "deepseek-chat"),
                system_prompt=(
                    "根据交易复盘生成简洁中文标题。"
                    '只输出 {"title":"沐曦放量突破"} 这种单字段 JSON。'
                ),
                user_prompt=_build_user_prompt(document),
                temperature=float(deepseek.get("temperature", 0.2)),
                timeout_seconds=float(deepseek.get("timeout_seconds", 20)),
                max_output_tokens=int(deepseek.get("max_output_tokens", 60)),
            )
            title = _provider_title(raw)
            return TitleSuggestion(title, "deepseek", False, None)
        except Exception as exc:
            return TitleSuggestion(
                _local_title(document),
                "local_fallback",
                True,
                str(exc),
            )


def _build_user_prompt(document: ReviewDocument) -> str:
    stocks = "、".join(stock.name for stock in document.stocks if stock.name.strip())
    tags = "、".join(document.tags)
    return (
        f"复盘日期：{document.review_date}\n"
        f"重点股票：{stocks}\n"
        f"标签：{tags}\n"
        f"正文：\n{document.body[:12000]}"
    )


def _provider_title(raw: object) -> str:
    if not isinstance(raw, dict) or not isinstance(raw.get("title"), str):
        raise ValueError("DeepSeek 标题 JSON 无效")
    title = _compact(raw["title"])
    if not title:
        raise ValueError("DeepSeek 标题为空")
    return title


def _local_title(document: ReviewDocument) -> str:
    names = _unique_nonempty(stock.name for stock in document.stocks)[:2]
    if names:
        return _limit_title("、".join(names))

    sentence = _first_body_sentence(document.body)
    if sentence:
        return _limit_title(sentence)

    tags = _unique_nonempty(document.tags)
    if tags:
        return _limit_title("、".join(tags))
    return _limit_title(document.title or f"{document.review_date} 交易复盘")


def _first_body_sentence(body: str) -> str:
    for line in body.splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        sentence = re.split(r"[。！？.!?]", text, maxsplit=1)[0]
        sentence = _compact(sentence)
        if sentence:
            return sentence
    return ""


def _unique_nonempty(values) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _compact(str(value))
        if text and text not in result:
            result.append(text)
    return result


def _limit_title(value: str) -> str:
    return _compact(value)[:30]


def _compact(value: str) -> str:
    return " ".join(value.split())
