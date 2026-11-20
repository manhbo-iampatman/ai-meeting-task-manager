from tests.conftest import auth, register


def test_weak_jwt_secret_refuses_to_start():
    import pytest

    from app.core.security import check_jwt_secret

    for weak in ("", "change-me", "doi-chuoi-nay-thanh-chuoi-ngau-nhien", "ngan-qua-31-ky-tu-xxxxxxxxxxxxx"):
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            check_jwt_secret(weak)
    check_jwt_secret("x" * 32)  # đủ 32 ký tự → chạy bình thường


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


def test_login_blocked_after_5_wrong_passwords(client):
    register(client, "d@example.com")
    wrong = {"email": "d@example.com", "password": "sai-mat-khau"}
    for _ in range(5):
        assert client.post("/api/auth/login", json=wrong).status_code == 401
    r = client.post("/api/auth/login", json=wrong)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert "15 phút" in r.json()["detail"]
    # Đang bị chặn thì gõ ĐÚNG cũng bị từ chối (kẻ dò không biết lúc nào trúng)
    right = {"email": "D@example.com", "password": "matkhau123"}
    assert client.post("/api/auth/login", json=right).status_code == 429
    # Tài khoản khác không bị ảnh hưởng
    register(client, "e@example.com")
    assert client.post("/api/auth/login", json={"email": "e@example.com", "password": "matkhau123"}).status_code == 200


def test_login_limiter_rules():
    from app.core.rate_limit import LoginLimiter

    now = [0.0]
    lim = LoginLimiter(max_fails=5, window_sec=900, block_sec=900, clock=lambda: now[0])
    # Sai 4 lần, đăng nhập đúng → xóa bộ đếm, sai tiếp 4 lần vẫn chưa bị chặn
    for _ in range(4):
        lim.record_failure("a@x.com", "1.1.1.1")
    lim.record_success("a@x.com", "1.1.1.1")
    for _ in range(4):
        lim.record_failure("a@x.com", "1.1.1.1")
    assert lim.retry_after("a@x.com", "1.1.1.1") == 0
    # Lần sai thứ 5 đến sau 15 phút → 4 lần sai cũ đã ra khỏi khung đếm, chỉ còn 1 lần → chưa chặn
    now[0] = 901
    lim.record_failure("a@x.com", "1.1.1.1")
    assert lim.retry_after("a@x.com", "1.1.1.1") == 0
    # Sai liền 5 lần → chặn 15 phút, chỉ chặn đúng cặp (email, IP) đó
    for _ in range(5):
        lim.record_failure("b@x.com", "1.1.1.1")
    assert lim.retry_after("B@x.com", "1.1.1.1") == 900
    assert lim.retry_after("b@x.com", "2.2.2.2") == 0  # máy khác vẫn đăng nhập được
    now[0] += 900
    assert lim.retry_after("b@x.com", "1.1.1.1") == 0  # hết 15 phút → mở chặn
