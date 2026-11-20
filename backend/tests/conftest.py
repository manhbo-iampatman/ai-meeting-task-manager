"""Cấu hình chung cho test: dùng CSDL riêng `meetflow_test`, làm sạch giữa các test."""

import os
import tempfile

TEST_DB = "meetflow_test"
os.environ["DATABASE_URL"] = f"postgresql+psycopg://meetflow:meetflow@localhost:5433/{TEST_DB}"
# File upload trong lúc test ghi vào thư mục tạm, không lẫn với dữ liệu thật
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="meetflow_test_uploads_")
# Khóa JWT riêng cho test → test không phụ thuộc file backend/.env của từng máy
os.environ["JWT_SECRET"] = "khoa-jwt-chi-dung-khi-chay-test-0123456789abcdef"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _ensure_test_database() -> None:
    with psycopg.connect("postgresql://meetflow:meetflow@localhost:5433/postgres", autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB}"')


_ensure_test_database()

from app import models  # noqa: E402, F401
from app.core.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    from app.core.rate_limit import login_limiter

    login_limiter.reset()  # bộ đếm đăng nhập sai không được lan từ test này sang test khác
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def register(client: TestClient, email: str, name: str = "Người dùng", password: str = "matkhau123") -> dict:
    r = client.post("/api/auth/register", json={"email": email, "password": password, "full_name": name})
    assert r.status_code == 201, r.text
    data = r.json()
    return {"Authorization": f"Bearer {data['access_token']}", "_user": data["user"]}


def auth(h: dict) -> dict:
    return {"Authorization": h["Authorization"]}
