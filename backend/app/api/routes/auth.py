"""F01–F02: đăng ký, đăng nhập, hồ sơ cá nhân."""

import math

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.rate_limit import login_limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UpdateMeIn
from app.schemas.common import UserBrief

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterIn, db: DB):
    email = data.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email đã được đăng ký")
    user = User(email=email, password_hash=hash_password(data.password), full_name=data.full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user.id), user=UserBrief.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: DB, request: Request):
    # Địa chỉ IP thật của người gọi. Đi qua Vite (proxy) thì uvicorn đọc header X-Forwarded-For
    # do Vite gắn vào (chỉ tin header này khi request đến từ chính máy chủ: 127.0.0.1 / ::1).
    ip = request.client.host if request.client else "unknown"
    wait = login_limiter.retry_after(data.email, ip)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Đăng nhập sai quá nhiều lần. Thử lại sau {math.ceil(wait / 60)} phút.",
            headers={"Retry-After": str(wait)},
        )
    user = db.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    # Cùng một thông báo cho "sai email" và "sai mật khẩu" → không lộ email nào đã đăng ký
    if user is None or not verify_password(data.password, user.password_hash):
        login_limiter.record_failure(data.email, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email hoặc mật khẩu không đúng")
    login_limiter.record_success(data.email, ip)
    return TokenOut(access_token=create_access_token(user.id), user=UserBrief.model_validate(user))


@router.get("/me", response_model=UserBrief)
def me(user: CurrentUser):
    return user


@router.patch("/me", response_model=UserBrief)
def update_me(data: UpdateMeIn, user: CurrentUser, db: DB):
    if data.full_name is not None:
        user.full_name = data.full_name.strip()
    if data.avatar_url is not None:
        user.avatar_url = data.avatar_url or None
    db.commit()
    db.refresh(user)
    return user
