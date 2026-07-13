"""验证默认 Web 后端必须注册复盘库接口。"""

from web.backend.main import app


def test_review_api_is_registered_on_default_app() -> None:
    """启动脚本使用的默认 FastAPI 应用必须能够处理复盘列表请求。"""
    assert any(route.path == "/api/reviews" for route in app.routes)
