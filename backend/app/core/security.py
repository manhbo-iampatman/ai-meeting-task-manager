"""Băm mật khẩu (bcrypt) và tạo / kiểm tra JWT.

- bcrypt: hàm băm MỘT CHIỀU, có "muối" (salt) ngẫu nhiên và cố tình chạy chậm
  → kẻ lấy được CSDL cũng không dịch ngược ra mật khẩu, khó dò bằng vét cạn.
- JWT (JSON Web Token): sau khi đăng nhập, server cấp 1 "vé" có chữ ký số.
  Mỗi request gửi kèm vé trong header `Authorization: Bearer <token>`.
  Server chỉ cần kiểm tra chữ ký là biết ai đang gọi — không cần lưu phiên.
"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE = timedelta(days=7)

# Khóa ký JWT quá yếu → ai đoán được khóa là tự "in vé" đăng nhập thành bất kỳ ai.
MIN_JWT_SECRET_LEN = 32
KNOWN_WEAK_SECRETS = {"", "change-me", "doi-chuoi-nay-thanh-chuoi-ngau-nhien"}  # mặc định / chuỗi mẫu


def check_jwt_secret(secret: str) -> None:
    """Gọi lúc backend khởi động: khóa yếu thì DỪNG luôn, không chạy (quyết định 20/11/2026)."""
    if secret in KNOWN_WEAK_SECRETS or len(secret) < MIN_JWT_SECRET_LEN:
        raise RuntimeError(
            f"JWT_SECRET trong backend/.env còn là giá trị mẫu hoặc ngắn hơn {MIN_JWT_SECRET_LEN} ký tự "
            "→ không an toàn, backend dừng. Tạo chuỗi ngẫu nhiên bằng lệnh:\n"
            '    python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
            "rồi dán vào dòng JWT_SECRET= trong backend/.env và chạy lại."
        )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + ACCESS_TOKEN_EXPIRE}
    return jwt.encode(payload, get_settings().JWT_SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Trả về user_id nếu token hợp lệ và chưa hết hạn, ngược lại None."""
    try:
        payload = jwt.decode(token, get_settings().JWT_SECRET, algorithms=[ALGORITHM])
        if "purpose" in payload:  # "vé" dùng cho 1 việc (vd. nghe ghi âm) KHÔNG phải vé đăng nhập
            return None
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


# ---------- "Vé" dùng cho đúng 1 việc ----------
# Thẻ <audio> không gửi được header Authorization → phải đặt vé trên đường link, mà link thì hay bị
# ghi vào log, lịch sử trình duyệt. Vì vậy KHÔNG đặt token đăng nhập lên link, chỉ đặt một vé
# "hẹp": chỉ mở được đúng file ghi âm của 1 cuộc họp, tự hết hạn. Lộ vé cũng không chiếm được
# tài khoản (quyết định 20/11/2026).


def create_scoped_token(user_id: int, purpose: str, ttl: timedelta, **claims: int | str) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "purpose": purpose, "iat": now, "exp": now + ttl, **claims}
    return jwt.encode(payload, get_settings().JWT_SECRET, algorithm=ALGORITHM)


def decode_scoped_token(token: str, purpose: str) -> dict | None:
    """Trả về nội dung vé nếu hợp lệ, chưa hết hạn và đúng mục đích; ngược lại None."""
    try:
        payload = jwt.decode(token, get_settings().JWT_SECRET, algorithms=[ALGORITHM])
        if payload.get("purpose") != purpose:
            return None
        payload["sub"] = int(payload["sub"])
        return payload
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
