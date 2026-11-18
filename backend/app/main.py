"""Điểm khởi động backend FastAPI.

Chạy:  uvicorn app.main:app --reload
Tài liệu API tự sinh (Swagger):  http://localhost:8000/docs
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, boards, health, meetings, names, notifications, realtime, tasks, workspaces
from app.core.config import get_settings
from app.core.realtime import redis_listener

settings = get_settings()
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khi backend khởi động: chạy nền tác vụ nghe sự kiện từ Redis (tiến độ từ worker AI)
    listener = asyncio.create_task(redis_listener())
    yield
    # Khi backend tắt: dừng tác vụ nền
    listener.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await listener


app = FastAPI(
    title=f"{settings.APP_NAME} API",
    description="Hệ thống quản lý công việc nhóm tích hợp AI tóm tắt cuộc họp và tạo đầu việc",
    version="0.5.0",
    lifespan=lifespan,
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
for r in (health, auth, workspaces, boards, tasks, meetings, names, notifications, realtime):
    app.include_router(r.router, prefix="/api")
