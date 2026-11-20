"""Realtime: WebSocket + Redis Pub/Sub.

1) ConnectionManager — quản lý các kết nối WebSocket theo "phòng":
   - "board:<id>"     : ai đang mở bảng Kanban
   - "workspace:<id>" : ai đang mở trang nhóm / trang cuộc họp (nhận tiến độ xử lý AI)
   Server gửi sự kiện tới mọi người trong phòng → trình duyệt tự tải lại dữ liệu.

2) Redis Pub/Sub — cầu nối giữa các TIẾN TRÌNH:
   Worker AI chạy ở tiến trình riêng, không chạm được vào danh sách WebSocket
   (nằm trong RAM của tiến trình backend). Nên worker `publish` sự kiện lên kênh
   Redis "meetflow:events"; backend `subscribe` kênh đó và chuyển tiếp tới WebSocket.

       Worker ──publish──► Redis ──subscribe──► Backend ──WebSocket──► Trình duyệt

   Cách này cũng cho phép chạy NHIỀU tiến trình backend sau này (mỗi tiến trình đều nghe Redis).
"""

import asyncio
import json
import logging
from collections import defaultdict

import redis
import redis.asyncio as aioredis
from fastapi import WebSocket

from app.core.config import get_settings

log = logging.getLogger(__name__)

EVENTS_CHANNEL = "meetflow:events"


def board_room(board_id: int) -> str:
    return f"board:{board_id}"


def workspace_room(workspace_id: int) -> str:
    return f"workspace:{workspace_id}"


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: dict[str, set[WebSocket]] = defaultdict(set)

    def join(self, room: str, ws: WebSocket) -> None:
        """Thêm kết nối (đã accept và đã xác thực xong) vào phòng."""
        self.rooms[room].add(ws)

    def disconnect(self, room: str, ws: WebSocket) -> None:
        self.rooms[room].discard(ws)
        if not self.rooms[room]:
            self.rooms.pop(room, None)

    async def broadcast(self, room: str, message: dict) -> None:
        sockets = list(self.rooms.get(room, ()))
        results = await asyncio.gather(*(ws.send_json(message) for ws in sockets), return_exceptions=True)
        for ws, r in zip(sockets, results, strict=True):
            if isinstance(r, Exception):  # kết nối đã chết → bỏ khỏi phòng
                self.disconnect(room, ws)


manager = ConnectionManager()


# ---------- Phía gửi (dùng được ở cả worker lẫn backend, code đồng bộ) ----------

_sync_redis: redis.Redis | None = None


def publish_event(room: str, message: dict) -> None:
    """Đẩy sự kiện lên Redis. Lỗi Redis không được làm hỏng công việc chính → chỉ ghi log."""
    global _sync_redis
    try:
        if _sync_redis is None:
            _sync_redis = redis.Redis.from_url(get_settings().REDIS_URL, socket_connect_timeout=2)
        _sync_redis.publish(EVENTS_CHANNEL, json.dumps({"room": room, "message": message}))
    except Exception as e:  # noqa: BLE001
        log.warning("Không publish được sự kiện realtime: %s", e)


# ---------- Phía nhận (chạy nền trong backend) ----------


async def redis_listener() -> None:
    """Nghe kênh Redis và chuyển tiếp sự kiện tới WebSocket. Tự kết nối lại nếu Redis mất."""
    while True:
        try:
            client = aioredis.Redis.from_url(get_settings().REDIS_URL)
            pubsub = client.pubsub()
            await pubsub.subscribe(EVENTS_CHANNEL)
            log.info("Đang nghe sự kiện realtime trên Redis")
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = json.loads(msg["data"])
                await manager.broadcast(data["room"], data["message"])
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Mất kết nối Redis (%s) — thử lại sau 3 giây", e)
            await asyncio.sleep(3)
