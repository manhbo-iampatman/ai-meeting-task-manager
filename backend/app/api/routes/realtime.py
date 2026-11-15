"""WebSocket: ws://.../api/ws/boards/{board_id}?token=<JWT>

Trình duyệt không gửi được header Authorization khi mở WebSocket, nên token
được truyền qua query string. Server kiểm tra token + quyền thành viên trước
khi cho vào "phòng" của bảng.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.database import SessionLocal
from app.core.realtime import manager
from app.core.security import decode_access_token
from app.models import Board, User, WorkspaceMember

router = APIRouter(tags=["realtime"])


def _can_access(board_id: int, token: str | None) -> bool:
    user_id = decode_access_token(token) if token else None
    if user_id is None:
        return False
    with SessionLocal() as db:
        board = db.get(Board, board_id)
        if board is None or db.get(User, user_id) is None:
            return False
        return db.get(WorkspaceMember, (board.workspace_id, user_id)) is not None


@router.websocket("/ws/boards/{board_id}")
async def board_socket(ws: WebSocket, board_id: int, token: str | None = None):
    if not _can_access(board_id, token):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await manager.connect(board_id, ws)
    try:
        while True:
            # Client có thể gửi "ping" để giữ kết nối; server không cần xử lý gì thêm
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(board_id, ws)
