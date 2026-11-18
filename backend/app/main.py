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

from app.api.routes import auth, boards, health, meetings, names, notifications, realtime, rooms, tasks, workspaces
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.realtime import redis_listener
from app.services import room_service

settings = get_settings()
logging.basicConfig(level=logging.INFO)


ROOM_WATCH_INTERVAL = 5  # giây


def _reconcile_rooms() -> None:
    with SessionLocal() as db:
        room_service.reconcile(db)


async def room_watcher() -> None:
    """Cứ 5 giây xem lại các phòng Online Meeting: phòng không còn ai thì tự đóng, chủ phòng vắng
    lâu thì nhượng quyền; phòng đã
    kết thúc thì chốt ghi âm (đủ người gửi về, hoặc đã chờ hết 2 phút) để đưa đi nhận dạng."""
    log = logging.getLogger("app.rooms")
    while True:
        await asyncio.sleep(ROOM_WATCH_INTERVAL)
        try:
            # Code CSDL là code đồng bộ → chạy ở luồng riêng để không chặn các request khác
            await asyncio.to_thread(_reconcile_rooms)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — CSDL / LiveKit tạm lỗi thì lần sau thử lại
            log.warning("Lỗi khi rà soát phòng họp: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khi backend khởi động: chạy nền tác vụ nghe sự kiện từ Redis (tiến độ từ worker AI)
    # và tác vụ rà soát phòng họp trực tuyến
    background = [asyncio.create_task(redis_listener()), asyncio.create_task(room_watcher())]
    yield
    # Khi backend tắt: dừng các tác vụ nền
    for task in background:
        task.cancel()
    for task in background:
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title=f"{settings.APP_NAME} API",
    description="Hệ thống quản lý công việc nhóm tích hợp AI tóm tắt cuộc họp và tạo đầu việc",
    version="0.6.0",
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
for r in (health, auth, workspaces, boards, tasks, meetings, rooms, names, notifications, realtime):
    app.include_router(r.router, prefix="/api")
