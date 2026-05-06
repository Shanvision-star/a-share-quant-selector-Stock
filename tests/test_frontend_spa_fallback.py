from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.main import mount_frontend


def test_spa_route_falls_back_to_index_html(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html>回测工作台</html>", encoding="utf-8")

    app = FastAPI()
    mount_frontend(app, dist_dir)

    response = TestClient(app).get("/backtest?source=manual&start=2026-04-24&end=2026-04-24")

    assert response.status_code == 200
    assert "回测工作台" in response.text
