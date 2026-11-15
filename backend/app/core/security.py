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
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
