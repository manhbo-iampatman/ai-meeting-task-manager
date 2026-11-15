from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Cho phép tạo schema trực tiếp từ object SQLAlchemy (from_attributes)."""

    model_config = ConfigDict(from_attributes=True)


class UserBrief(ORMModel):
    id: int
    email: str
    full_name: str
    avatar_url: str | None = None
