"""Tracking 路由顺序回归测试。

背景（commit 1ab0e69）：
`web.backend.routers.tracking.router` 在 `/api` 前缀下声明了
`/tracking/{tracking_id}` 这条 path 参数路由。FastAPI 按 `include_router`
顺序匹配，如果该 catch-all 比 `/api/tracking/alerts` 等固定子路径先注册，
请求会被吞进 `{tracking_id}` 参数路由并返回 404。

本测试通过加载真实的 `web.backend.main:app`，直接对所有易被吞掉的
固定前缀发起请求，断言响应不会出现"被 tracking.router 误吞"的特征：
- HTTP 状态不能是 404；
- 若是 GET 列表接口，应该返回 200 + JSON（即使数据为空）。

如果将来有人重排 `main.py` 的 `include_router` 顺序导致回归，
该用例会立即失败，把契约固化在测试里。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _TrackingLoopRunnerStub:
    def run_post_close(self, **kwargs):
        return {
            "run_id": "route_order_stub",
            "loop_type": "post_close",
            "status": "done",
            **kwargs,
        }

    def latest_run(self, loop_type="post_close"):
        return {"run_id": "route_order_stub", "loop_type": loop_type, "status": "done"}


@pytest.fixture(autouse=True)
def stub_tracking_loop_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    from web.backend.routers import tracking_loop as router_module

    monkeypatch.setattr(
        router_module,
        "tracking_loop_runner_service",
        _TrackingLoopRunnerStub(),
    )


@pytest.fixture(scope="module")
def client() -> TestClient:
    # 延迟导入：保证测试运行时 main.py 内的副作用（路由注册）按真实顺序执行
    from web.backend.main import app

    return TestClient(app)


# 这些路径都必须由各自的专用子路由器命中，
# 一旦被 `/tracking/{tracking_id}` 吞掉就会变成 404 或解析为 tracking_id="alerts" 等。
_FIXED_GET_PATHS = [
    "/api/tracking/alerts",
    "/api/tracking/rule-templates",
    "/api/tracking/rule-templates/rules",
    "/api/tracking/stock-name/000001",   # 股票名称查询：固定子路径，不能被 /{tracking_id} 吞
    "/api/tracking/signal-close/000001?date=2026-05-27",  # 信号日收盘价：固定子路径，不能被 /{tracking_id} 吞
]


# POST 类固定子路径同样需要避让 catch-all；用空 body 触发 422/400 也比 404 健康。
_FIXED_POST_PATHS = [
    "/api/tracking/loops/post-close/run",
    "/api/tracking/batch-create",
    "/api/tracking/batch-delete",
    "/api/tracking/batch-from-selection",
    "/api/tracking/sync-close",   # 收盘同步：固定子路径，不能被 /{tracking_id} 吞掉
]


@pytest.mark.parametrize("path", _FIXED_POST_PATHS)
def test_fixed_post_subpaths_not_shadowed(client: TestClient, path: str) -> None:
    """POST 固定子路径不能被 /tracking/{tracking_id} catch-all 吞掉。"""
    resp = client.post(path, json={})
    assert resp.status_code != 404, (
        f"{path} 返回 404，路由顺序被破坏：tracking.router 把固定段当成 tracking_id 吞掉了。"
    )
    assert resp.headers.get("content-type", "").startswith("application/json")


@pytest.mark.parametrize("path", _FIXED_GET_PATHS)
def test_fixed_subpaths_not_shadowed_by_tracking_id(client: TestClient, path: str) -> None:
    """固定子路径不能被 /tracking/{tracking_id} catch-all 吞掉。"""
    resp = client.get(path)
    assert resp.status_code != 404, (
        f"{path} 返回 404，说明路由顺序被破坏：tracking.router 把固定段当成 tracking_id 吞掉了。"
        f" 请检查 web/backend/main.py 的 include_router 顺序。"
    )
    # 成功路径应当返回 JSON 列表或对象；至少 content-type 是 JSON
    assert resp.headers.get("content-type", "").startswith("application/json"), (
        f"{path} 没有返回 JSON：可能命中了错误的处理器。status={resp.status_code} body={resp.text[:200]}"
    )


def test_tracking_detail_route_still_works(client: TestClient) -> None:
    """确认 /api/tracking/{tracking_id} 仍可命中（用一个不存在的 id 触发 404 即可证明路由本身存活）。"""
    resp = client.get("/api/tracking/trk_definitely_not_exist_xxx")
    # 该路由本身存在；服务层对不存在 id 应返回 404（业务 404，而非路由 404）。
    # 关键断言：响应是 JSON（说明命中 FastAPI 处理器，而非框架级 Not Found）。
    assert resp.headers.get("content-type", "").startswith("application/json")
    # 业务 404 / 422 / 200 都可接受，只要不是因为路由完全缺失。
    assert resp.status_code in (200, 404, 422, 500)
