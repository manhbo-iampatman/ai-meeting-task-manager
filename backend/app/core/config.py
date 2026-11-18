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
    GEMINI_MODEL: str = "gemini-3.5-flash"
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    OLLAMA_NUM_CTX: int = 8192  # số token mô hình Ollama đọc được mỗi lần gọi
    OLLAMA_KEEP_ALIVE: str = "30s"  # giữ mô hình trong VRAM bao lâu sau khi trả lời
    LLM_TEMPERATURE: float = 0.2  # thấp = kết quả ổn định giữa các lần chạy
    # Mô hình chính quá tải / hết hạn mức (429, 503, 504, hết thời gian chờ) → tự chuyển sang
    # mô hình này. Để trống = không dùng dự phòng.
    GEMINI_FALLBACK_MODEL: str = "gemini-3.5-flash-lite"
    # Chờ Gemini tối đa bao lâu cho mỗi lần gọi. Lúc bình thường 1 lần gọi mất 3–20 giây;
    # quá ngưỡng này thì coi như mô hình đang quá tải.
    LLM_TIMEOUT_SEC: int = 60
    # Giới hạn ký tự mỗi đoạn khi chia bản ghi dài. 0 = dùng mặc định của từng mô hình.
    LLM_CHUNK_CHARS: int = 0
    GROQ_API_KEY: str = ""

    # --- Phòng họp trực tuyến "Online Meeting" (LiveKit) ---
    LIVEKIT_URL: str = "http://localhost:7880"  # backend gọi API quản lý phòng của LiveKit ở đây
    # Cặp khóa dùng chung với LiveKit (docker-compose.yml). scripts/setup_lan.py sinh khóa ngẫu nhiên.
    LIVEKIT_API_KEY: str = "devkey"
    LIVEKIT_API_SECRET: str = "meetflow-dev-secret-chi-dung-tren-may-minh-0123456789"
    ROOM_MAX_PARTICIPANTS: int = 6
    ROOM_EMPTY_CLOSE_SEC: int = 30  # mọi người rời hết quá 30 giây → tự đóng phòng
    # Phòng được tạo ngay lúc người mở bấm "Vào phòng". Tạo xong mà không ai vào được (lỗi kết nối…)
    # thì đóng sau 1 phút.
    ROOM_UNJOINED_CLOSE_SEC: int = 60
    ROOM_HOST_ABSENT_SEC: int = 60  # chủ phòng vắng quá 1 phút (phòng còn người) → nhượng quyền chủ phòng
    ROOM_UPLOAD_WAIT_SEC: int = 120  # phòng kết thúc → chờ ghi âm của mọi người tối đa 2 phút

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Đọc cấu hình 1 lần rồi cache lại (lru_cache)."""
    return Settings()
