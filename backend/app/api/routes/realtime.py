"""WebSocket:
  ws://.../api/ws/boards/{board_id}?token=<JWT>          — cập nhật bảng Kanban
  ws://.../api/ws/workspaces/{workspace_id}?token=<JWT>  — tiến độ xử lý cuộc họp của nhóm

Trình duyệt không gửi được header Authorization khi mở WebSocket, nên token
được truyền qua query string. Server kiểm tra token + quyền thành viên trước
khi cho vào "phòng".
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.database import SessionLocal
from app.core.realtime import board_room, manager, workspace_room
from app.core.security import decode_access_token
from app.models import Board, User, WorkspaceMember

router = APIRouter(tags=["realtime"])


def _is_member(workspace_id: int | None, token: str | None) -> bool:
    user_id = decode_access_token(token) if token else None
    if user_id is None or workspace_id is None:
        return False
    with SessionLocal() as db:
        if db.get(User, user_id) is None:
            return False
        return db.get(WorkspaceMember, (workspace_id, user_id)) is not None


def _board_workspace(board_id: int) -> int | None:
    with SessionLocal() as db:
        board = db.get(Board, board_id)
        return board.workspace_id if board else None


async def _serve(ws: WebSocket, room: str) -> None:
    await manager.connect(room, ws)
    try:
        while True:
            # Client có thể gửi "ping" để giữ kết nối; server không cần xử lý gì thêm
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room, ws)


@router.websocket("/ws/boards/{board_id}")
async def board_socket(ws: WebSocket, board_id: int, token: str | None = None):
    if not _is_member(_board_workspace(board_id), token):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await _serve(ws, board_room(board_id))


@router.websocket("/ws/workspaces/{workspace_id}")
async def workspace_socket(ws: WebSocket, workspace_id: int, token: str | None = None):
    if not _is_member(workspace_id, token):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await _serve(ws, workspace_room(workspace_id))
