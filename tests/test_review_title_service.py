"""验证复盘标题候选的 provider 边界和本地回退。"""

from dataclasses import replace

import pytest

from web.backend.services.review_repository import ReviewDocument, ReviewStock
from web.backend.services import review_title_service as title_module


def _document(*, body: str = "市场情绪回暖，半导体板块放量。", stocks=(), tags=()) -> ReviewDocument:
    return replace(
        ReviewDocument.new("2026-07-11"),
        body=body,
        stocks=stocks,
        tags=tags,
    )


def _deepseek_config() -> dict:
    return {
        "provider": "deepseek",
        "deepseek": {
            "api_key": "test-key",
            "base_url": "http://example.test/v1",
            "model": "deepseek-chat",
        },
    }


def test_generate_uses_deepseek_title_when_provider_returns_valid_payload(monkeypatch) -> None:
    """有效单字段 JSON 标题保留 DeepSeek 来源。"""
    monkeypatch.setattr(title_module, "load_llm_config", _deepseek_config)
    monkeypatch.setattr(title_module, "call_deepseek", lambda **_kwargs: {"title": "沐曦股份放量突破"})

    suggestion = title_module.ReviewTitleService().generate(
        _document(stocks=(ReviewStock(code="688802", name="沐曦股份"),))
    )

    assert suggestion.title == "沐曦股份放量突破"
    assert suggestion.source == "deepseek"
    assert suggestion.provider_fallback is False
    assert suggestion.provider_error is None


def test_generate_falls_back_to_stock_names_when_deepseek_is_not_configured(monkeypatch) -> None:
    """离线或未配置 provider 时不调用网络，优先使用最多两个股票名称。"""
    monkeypatch.setattr(title_module, "load_llm_config", lambda: {"provider": "mock"})

    suggestion = title_module.ReviewTitleService().generate(
        _document(
            stocks=(
                ReviewStock(code="688802", name="沐曦股份"),
                ReviewStock(code="688256", name="寒武纪"),
                ReviewStock(code="000001", name="平安银行"),
            )
        )
    )

    assert suggestion.source == "local_fallback"
    assert suggestion.provider_fallback is True
    assert "沐曦股份" in suggestion.title
    assert "寒武纪" in suggestion.title
    assert "平安银行" not in suggestion.title


def test_generate_falls_back_to_first_sentence_after_provider_timeout(monkeypatch) -> None:
    """provider 超时后使用正文首个有效非标题句子。"""
    monkeypatch.setattr(title_module, "load_llm_config", _deepseek_config)

    def raise_timeout(**_kwargs):
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(title_module, "call_deepseek", raise_timeout)

    suggestion = title_module.ReviewTitleService().generate(
        _document(body="# 交易复盘\n\n市场情绪回暖，半导体板块放量。")
    )

    assert suggestion.source == "local_fallback"
    assert suggestion.provider_fallback is True
    assert "市场情绪回暖" in suggestion.title
    assert suggestion.provider_error == "provider_unavailable"
    assert suggestion.provider_exception_type == "TimeoutError"


def test_generate_falls_back_to_tags_for_invalid_provider_json(monkeypatch) -> None:
    """非法 JSON 等价的无效 provider payload 不能污染标题候选。"""
    monkeypatch.setattr(title_module, "load_llm_config", _deepseek_config)
    monkeypatch.setattr(title_module, "call_deepseek", lambda **_kwargs: {"title": ["不是字符串"]})

    suggestion = title_module.ReviewTitleService().generate(
        _document(body="", tags=("B1", "半导体"))
    )

    assert suggestion.source == "local_fallback"
    assert suggestion.provider_fallback is True
    assert "B1" in suggestion.title
    assert suggestion.provider_error is not None


@pytest.mark.parametrize("provider_title", ["短标题七个字", "超" * 31])
def test_generate_falls_back_when_deepseek_title_is_outside_length_bounds(
    monkeypatch,
    provider_title: str,
) -> None:
    """DeepSeek 标题少于 8 字或超过 30 字时必须走本地回退。"""
    monkeypatch.setattr(title_module, "load_llm_config", _deepseek_config)
    monkeypatch.setattr(title_module, "call_deepseek", lambda **_kwargs: {"title": provider_title})

    suggestion = title_module.ReviewTitleService().generate(_document(body="市场情绪回暖，成交量温和放大。"))

    assert suggestion.source == "local_fallback"
    assert suggestion.provider_fallback is True
    assert suggestion.title != provider_title


@pytest.mark.parametrize("provider_title", ["有效标题八个字整", "满" * 30])
def test_generate_accepts_deepseek_title_at_inclusive_length_bounds(
    monkeypatch,
    provider_title: str,
) -> None:
    """DeepSeek 标题的 8 字与 30 字边界均应被接受。"""
    monkeypatch.setattr(title_module, "load_llm_config", _deepseek_config)
    monkeypatch.setattr(title_module, "call_deepseek", lambda **_kwargs: {"title": provider_title})

    suggestion = title_module.ReviewTitleService().generate(_document())

    assert suggestion.title == provider_title
    assert suggestion.source == "deepseek"
