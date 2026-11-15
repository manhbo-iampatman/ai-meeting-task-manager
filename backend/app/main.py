"""Điểm khởi động backend FastAPI.

Chạy:  uvicorn app.main:app --reload
Tài liệu API tự sinh (Swagger):  http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=f"{settings.APP_NAME} API",
    description="Hệ thống quản lý công việc nhóm tích hợp AI tóm tắt cuộc họp và tạo đầu việc",
    version="0.1.0",
)

# CORS: cho phép frontend (khác cổng, localhost:5173) gọi API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mọi API đều có tiền tố /api
app.include_router(health.router, prefix="/api")
