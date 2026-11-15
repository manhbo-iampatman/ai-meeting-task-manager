"""Cấu hình ứng dụng.

Mọi giá trị đọc từ biến môi trường / file .env (thư viện pydantic-settings).
Lợi ích: không ghi cứng mật khẩu, API key vào code; đổi môi trường (máy dev,
server) chỉ cần đổi file .env.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "MeetFlow"
    DEBUG: bool = True

    DATABASE_URL: str = "postgresql+psycopg://meetflow:meetflow@localhost:5433/meetflow"
    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET: str = "change-me"
    CORS_ORIGINS: str = "http://localhost:5173"

    UPLOAD_DIR: str = "uploads"

    # --- AI ---
    STT_PROVIDER: Literal["local", "groq"] = "local"
    WHISPER_MODEL: str = "large-v3-turbo"
    WHISPER_DEVICE: Literal["cuda", "cpu", "auto"] = "cuda"
    WHISPER_COMPUTE_TYPE: str = "int8_float16"
    WHISPER_MODEL_DIR: str = "models_cache"

    LLM_PROVIDER: Literal["gemini", "ollama"] = "gemini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    GROQ_API_KEY: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Đọc cấu hình 1 lần rồi cache lại (lru_cache)."""
    return Settings()
