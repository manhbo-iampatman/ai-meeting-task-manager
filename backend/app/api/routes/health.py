"""API kiểm tra "sức khỏe" hệ thống: backend, PostgreSQL, Redis, GPU.

Dùng ở Giai đoạn 0 để biết các thành phần đã chạy chưa. Không bao giờ
làm sập API — thành phần nào lỗi thì báo "error" kèm lý do.
"""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.core.queue import redis_conn

router = APIRouter(tags=["health"])


def _check_database() -> dict:
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar_one()
        return {"status": "ok", "detail": version.split(",")[0]}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"{type(e).__name__} — đã chạy 'docker compose up -d' chưa?"}


def _check_redis() -> dict:
    try:
        redis_conn.ping()
        return {"status": "ok", "detail": f"Redis {redis_conn.info('server')['redis_version']}"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"{type(e).__name__} — đã chạy 'docker compose up -d' chưa?"}


def _check_gpu() -> dict:
    """Kiểm tra GPU qua CTranslate2 (thư viện lõi của faster-whisper)."""
    try:
        import ctranslate2

        n = ctranslate2.get_cuda_device_count()
        if n > 0:
            return {"status": "ok", "detail": f"{n} GPU CUDA khả dụng"}
        return {"status": "error", "detail": "Không thấy GPU CUDA"}
    except ImportError:
        return {"status": "not_installed", "detail": "Chưa cài requirements-ai.txt"}


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "app": s.APP_NAME,
        "backend": {"status": "ok"},
        "database": _check_database(),
        "redis": _check_redis(),
        "gpu": _check_gpu(),
        "ai_config": {"stt": s.STT_PROVIDER, "whisper_model": s.WHISPER_MODEL, "llm": s.LLM_PROVIDER},
    }
