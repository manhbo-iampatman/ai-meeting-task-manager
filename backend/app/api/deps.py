"""Các "dependency" dùng chung cho route: lấy user đang đăng nhập, kiểm tra quyền.

FastAPI tự gọi các hàm này trước khi vào route (Dependency Injection), nhờ vậy
route không phải lặp lại code kiểm tra token / quyền thành viên.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import Board, BoardColumn, Task, User, Workspace, WorkspaceMember

bearer = HTTPBearer(auto_error=False)

DB = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chưa đăng nhập")
    user_id = decode_access_token(creds.credentials)
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# ---------- Kiểm tra quyền theo nhóm ----------


def get_membership(db: Session, workspace_id: int, user: User) -> WorkspaceMember:
    """Trả về tư cách thành viên; 404 nếu nhóm không tồn tại hoặc user không thuộc nhóm.

    Trả 404 (thay vì 403) để người ngoài không dò được nhóm nào đang tồn tại.
    """
    m = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id
        )
    )
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy nhóm")
    return m


def require_owner(m: WorkspaceMember) -> None:
    if m.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ trưởng nhóm được làm thao tác này")


def get_workspace_for_member(db: Session, workspace_id: int, user: User) -> tuple[Workspace, WorkspaceMember]:
    m = get_membership(db, workspace_id, user)
    return m.workspace, m


def get_board_for_member(db: Session, board_id: int, user: User) -> Board:
    board = db.get(Board, board_id)
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy bảng")
    get_membership(db, board.workspace_id, user)
    return board


def get_column_for_member(db: Session, column_id: int, user: User) -> BoardColumn:
    col = db.get(BoardColumn, column_id)
    if col is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy cột")
    get_board_for_member(db, col.board_id, user)
    return col


def get_task_for_member(db: Session, task_id: int, user: User) -> tuple[Task, Board]:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy công việc")
    board = get_board_for_member(db, task.board_id, user)
    return task, board


def can_edit_task(db: Session, task: Task, board: Board, user: User) -> bool:
    """Ai được kéo thả / sửa / xóa thẻ: người làm, người tạo thẻ, trưởng nhóm (quyết định 18/11/2026).

    Thẻ chưa có người làm hoặc giao theo tên chữ → chỉ người tạo thẻ + trưởng nhóm.
    Thành viên khác vẫn xem và bình luận được.
    """
    if user.id in (task.assignee_id, task.created_by):
        return True
    ws = db.get(Workspace, board.workspace_id)
    return ws is not None and ws.owner_id == user.id


def require_task_editor(db: Session, task: Task, board: Board, user: User) -> None:
    if not can_edit_task(db, task, board, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Chỉ người làm, người tạo thẻ hoặc trưởng nhóm được thay đổi thẻ này"
        )


def ensure_member_user(db: Session, workspace_id: int, user_id: int | None) -> None:
    """Người được giao việc phải là thành viên của nhóm."""
    if user_id is None:
        return
    exists = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
        )
    )
    if exists is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Người được giao không phải thành viên nhóm")
