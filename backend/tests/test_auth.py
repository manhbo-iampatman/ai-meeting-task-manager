from tests.conftest import auth, register


def test_register_login_me(client):
    h = register(client, "nam@example.com", "Nguyễn Văn Nam")
    r = client.get("/api/auth/me", headers=auth(h))
    assert r.status_code == 200
    assert r.json()["full_name"] == "Nguyễn Văn Nam"

    r = client.post("/api/auth/login", json={"email": "NAM@example.com", "password": "matkhau123"})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_duplicate_email(client):
    register(client, "a@example.com")
    r = client.post("/api/auth/register", json={"email": "A@example.com", "password": "matkhau123", "full_name": "X"})
    assert r.status_code == 409


def test_wrong_password_and_no_token(client):
    register(client, "b@example.com")
    r = client.post("/api/auth/login", json={"email": "b@example.com", "password": "sai-mat-khau"})
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_password_is_hashed(client):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import User

    register(client, "c@example.com", password="matkhau123")
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "c@example.com"))
        assert u.password_hash != "matkhau123"
        assert u.password_hash.startswith("$2")  # định dạng bcrypt
