"""Quản lý kết nối WebSocket để cập nhật bảng theo thời gian thực.

Ý tưởng: mỗi bảng là 1 "phòng". Ai đang mở bảng thì kết nối WebSocket vào phòng
đó. Khi có thay đổi (thêm/sửa/kéo thẻ), server gửi sự kiện tới mọi người trong
phòng → trình duyệt của họ tải lại dữ liệu bảng.

So với "polling" (trình duyệt cứ vài giây hỏi server 1 lần): WebSocket giữ một
kết nối mở 2 chiều, server CHỦ ĐỘNG đẩy tin → cập nhật tức thì, ít request thừa.

Giới hạn: danh sách kết nối nằm trong RAM của 1 tiến trình. Nếu chạy nhiều
tiến trình backend thì cần Redis Pub/Sub để chia sẻ (hướng phát triển).
"""

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, board_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self.rooms[board_id].add(ws)

    def disconnect(self, board_id: int, ws: WebSocket) -> None:
        self.rooms[board_id].discard(ws)
        if not self.rooms[board_id]:
            self.rooms.pop(board_id, None)

    async def broadcast(self, board_id: int, message: dict) -> None:
        sockets = list(self.rooms.get(board_id, ()))
        results = await asyncio.gather(*(ws.send_json(message) for ws in sockets), return_exceptions=True)
        for ws, r in zip(sockets, results, strict=True):
            if isinstance(r, Exception):  # kết nối đã chết → bỏ khỏi phòng
                self.disconnect(board_id, ws)


manager = ConnectionManager()
