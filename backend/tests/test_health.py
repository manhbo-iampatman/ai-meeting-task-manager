from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_always_responds():
    """API /api/health phải trả 200 kể cả khi DB/Redis chưa chạy."""
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["backend"]["status"] == "ok"
    for key in ("database", "redis", "gpu"):
        assert body[key]["status"] in {"ok", "error", "not_installed"}
