"""WebSocket:
  ws://.../api/ws/boards/{board_id}          — cập nhật bảng Kanban
  ws://.../api/ws/workspaces/{workspace_id}  — tiến độ xử lý cuộc họp của nhóm

Trình duyệt không gửi được header Authorization khi mở WebSocket. Trước đây token được đặt
trên đường link (?token=...), nhưng link bị ghi vào log server → lộ token. Nay (20/11/2026):

    Trình duyệt ──mở kết nối (link KHÔNG có token)──► Server  (accept)
    Trình duyệt ──tin nhắn đầu: {"type":"auth","token":"<JWT>"}──► Server
    Server kiểm tra token + quyền thành viên:
        đúng → gửi {"type":"auth_ok"} rồi cho vào "phòng"
        sai / quá 10 giây chưa gửi → đóng kết nối (mã 1008)
"""

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.database import SessionLocal
from app.core.realtime import board_room, manager, workspace_room
from app.core.security import decode_access_token
from app.models import Board, User, WorkspaceMember

router = APIRouter(tags=["realtime"])

AUTH_TIMEOUT_SEC = 10  # mở kết nối xong phải gửi token trong vòng 10 giây


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


async def _read_auth_token(ws: WebSocket) -> str | None:
    """Đọc tin nhắn đầu tiên {"type": "auth", "token": "..."}; sai dạng / quá hạn → None."""
    try:
        raw = await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_SEC)
        msg = json.loads(raw)
    except (TimeoutError, ValueError, KeyError, WebSocketDisconnect):  # KeyError: gửi dữ liệu nhị phân
        return None
    if not isinstance(msg, dict) or msg.get("type") != "auth" or not isinstance(msg.get("token"), str):
        return None
    return msg["token"]


async def _serve(ws: WebSocket, room: str, workspace_id_of) -> None:
    """workspace_id_of: hàm trả về id nhóm của "phòng" (để kiểm tra quyền thành viên)."""
    await ws.accept()
    token = await _read_auth_token(ws)
    # Code CSDL là code đồng bộ → chạy ở luồng riêng để không chặn các kết nối khác
    allowed = token is not None and await asyncio.to_thread(lambda: _is_member(workspace_id_of(), token))
    if not allowed:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):  # trình duyệt đã tự ngắt trước
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.send_json({"type": "auth_ok"})
    manager.join(room, ws)
    try:
        while True:
            # Client có thể gửi "ping" để giữ kết nối; server không cần xử lý gì thêm
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room, ws)


@router.websocket("/ws/boards/{board_id}")
async def board_socket(ws: WebSocket, board_id: int):
    await _serve(ws, board_room(board_id), lambda: _board_workspace(board_id))


@router.websocket("/ws/workspaces/{workspace_id}")
async def workspace_socket(ws: WebSocket, workspace_id: int):
    await _serve(ws, workspace_room(workspace_id), lambda: workspace_id)
