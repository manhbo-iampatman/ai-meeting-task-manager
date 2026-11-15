"""Schema (Pydantic) = "hợp đồng" dữ liệu vào/ra của API.

FastAPI tự kiểm tra dữ liệu gửi lên theo schema; sai định dạng → trả lỗi 422
kèm lý do, route không cần tự viết code kiểm tra.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import UserBrief


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=64)
    full_name: str = Field(min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def bcrypt_limit(cls, v: str) -> str:
        # bcrypt chỉ xử lý tối đa 72 byte (ký tự tiếng Việt có dấu chiếm 2-3 byte)
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Mật khẩu quá dài")
        return v

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Họ tên không được để trống")
        return v


class LoginIn(BaseModel):
    # Đăng nhập chỉ cần so khớp với tài khoản đã có → không kiểm tra định dạng email
    email: str = Field(min_length=1, max_length=255)
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserBrief


class UpdateMeIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=500)
