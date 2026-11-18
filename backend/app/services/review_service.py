"""F17 — Duyệt đầu việc nháp và "Đẩy lên bảng" (Giai đoạn 5).

Kết quả AI chỉ là ĐỀ XUẤT (bảng `extracted_tasks`). Người duyệt sửa, bỏ tick, rồi bấm
"Đẩy lên bảng" → các việc được tick trở thành thẻ thật trên Kanban, trong MỘT transaction:
hoặc tạo được hết, hoặc không tạo thẻ nào (không bao giờ đẩy được một nửa).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.models import Board, BoardColumn, ExtractedTask, ExtractedTaskStatus, Meeting, MeetingStatus, Task, User, Workspace
from app.services.board_service import position_at_index
from app.services.notification_service import notify_assigned


def can_review(db: Session, meeting: Meeting, user: User) -> bool:
    """Ai được duyệt và đẩy lên bảng: trưởng nhóm + người tải cuộc họp lên."""
    if meeting.created_by == user.id:
        return True
    ws = db.get(Workspace, meeting.workspace_id)
    return ws is not None and ws.owner_id == user.id


def require_reviewer(db: Session, meeting: Meeting, user: User) -> None:
    if not can_review(db, meeting, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ trưởng nhóm hoặc người tải cuộc họp lên được duyệt đầu việc")


def first_column(db: Session, board: Board) -> BoardColumn:
    col = db.scalar(select(BoardColumn).where(BoardColumn.board_id == board.id).order_by(BoardColumn.position).limit(1))
    if col is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bảng này chưa có cột nào")
    return col


def push_to_board(db: Session, meeting: Meeting, board: Board, actor: User) -> list[Task]:
    """Tạo thẻ cho mọi đầu việc chưa đẩy đang được tick; việc không tick → "đã bỏ".

    Chỉ `flush`, KHÔNG `commit`: route gọi commit một lần ở cuối → cả lần đẩy là một transaction.
    """
    if board.workspace_id != meeting.workspace_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bảng không thuộc nhóm của cuộc họp")
    if meeting.status in MeetingStatus.PROCESSING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cuộc họp đang được xử lý")

    drafts = [d for d in meeting.extracted_tasks if d.status != ExtractedTaskStatus.ACCEPTED]
    chosen = [d for d in drafts if d.selected]
    if not chosen:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chưa chọn đầu việc nào để đẩy lên bảng")

    col = first_column(db, board)
    n = db.scalar(select(func.count()).where(Task.column_id == col.id)) or 0
    created: list[Task] = []
    for i, d in enumerate(chosen):
        task = Task(
            board_id=board.id,
            column_id=col.id,
            title=d.title,
            assignee_id=d.assignee_id,
            assignee_name=None if d.assignee_id else d.assignee_name,
            due_date=d.due_date,
            priority=d.priority,
            position=position_at_index(db, col.id, n + i),
            created_by=actor.id,
            meeting_id=meeting.id,
        )
        db.add(task)
        db.flush()  # để có task.id (cần cho thông báo + liên kết ngược)
        d.status, d.task_id = ExtractedTaskStatus.ACCEPTED, task.id
        notify_assigned(db, task, board, actor)
        created.append(task)

    for d in drafts:
        if not d.selected:
            d.status = ExtractedTaskStatus.REJECTED
    meeting.status = MeetingStatus.DONE
    db.flush()
    return created
