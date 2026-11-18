"""F05–F07: thẻ công việc, kéo-thả, bình luận, "việc của tôi". F20: giao theo tên. F18: nguồn gốc thẻ."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import func, select

from app.api.deps import (
    DB,
    CurrentUser,
    ensure_member_user,
    get_board_for_member,
    get_task_for_member,
    require_task_editor,
)
from app.api.routes.boards import board_changed
from app.core.realtime import publish_event, workspace_room
from app.models import Board, BoardColumn, ExtractedTask, Meeting, Task, TaskComment, Workspace, WorkspaceMember
from app.schemas.board import (
    CommentCreate,
    CommentOut,
    MyTaskOut,
    TaskCreate,
    TaskDetail,
    TaskMove,
    TaskOut,
    TaskSource,
    TaskUpdate,
)
from app.services.board_service import position_at_index
from app.services.notification_service import notify_assigned

router = APIRouter(tags=["tasks"])


def _column_of_board(db: DB, column_id: int, board_id: int) -> BoardColumn:
    col = db.get(BoardColumn, column_id)
    if col is None or col.board_id != board_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cột không thuộc bảng này")
    return col


def _clean_name(name: str | None) -> str | None:
    """F20: tên người làm dạng chữ — bỏ khoảng trắng thừa, rỗng thì coi như không có."""
    name = " ".join((name or "").split())
    return name[:100] or None


def _names_changed(board: Board) -> None:
    """Danh sách "tên chưa có người nhận" của nhóm thay đổi → trang nhóm tải lại (F21)."""
    publish_event(workspace_room(board.workspace_id), {"type": "names_updated"})


def _source(db: DB, task: Task) -> TaskSource | None:
    """F18: cuộc họp + câu nói đã sinh ra thẻ này."""
    if task.meeting_id is None:
        return None
    m = db.get(Meeting, task.meeting_id)
    if m is None:
        return None
    d = db.scalar(select(ExtractedTask).where(ExtractedTask.task_id == task.id).limit(1))
    return TaskSource(
        meeting_id=m.id,
        meeting_title=m.title,
        meeting_date=m.meeting_date,
        evidence_quote=d.evidence_quote if d and d.evidence_found else None,
        evidence_start=d.evidence_start if d and m.audio_path else None,
    )


def _task_detail(db: DB, task: Task) -> TaskDetail:
    comments = db.scalars(
        select(TaskComment).where(TaskComment.task_id == task.id).order_by(TaskComment.created_at)
    ).all()
    out = TaskDetail.model_validate(task)
    out.comments = [CommentOut.model_validate(c) for c in comments]
    out.comment_count = len(comments)
    col = db.get(BoardColumn, task.column_id)
    out.column_name = col.name if col else ""
    out.source = _source(db, task)
    return out


@router.post("/boards/{board_id}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(board_id: int, data: TaskCreate, user: CurrentUser, db: DB, background: BackgroundTasks):
    board = get_board_for_member(db, board_id, user)
    _column_of_board(db, data.column_id, board.id)
    ensure_member_user(db, board.workspace_id, data.assignee_id)

    # Thẻ mới được đặt ở cuối cột
    n = db.scalar(select(func.count()).where(Task.column_id == data.column_id))
    task = Task(
        board_id=board.id,
        column_id=data.column_id,
        title=data.title.strip(),
        description=data.description,
        assignee_id=data.assignee_id,
        assignee_name=None if data.assignee_id else _clean_name(data.assignee_name),
        due_date=data.due_date,
        priority=data.priority,
        position=position_at_index(db, data.column_id, n),
        created_by=user.id,
    )
    db.add(task)
    db.flush()
    notify_assigned(db, task, board, user)
    db.commit()
    db.refresh(task)
    board_changed(background, board.id, user.id)
    if task.assignee_name:
        _names_changed(board)
    return task


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: int, user: CurrentUser, db: DB):
    task, _ = get_task_for_member(db, task_id, user)
    return _task_detail(db, task)


@router.patch("/tasks/{task_id}", response_model=TaskDetail)
def update_task(task_id: int, data: TaskUpdate, user: CurrentUser, db: DB, background: BackgroundTasks):
    task, board = get_task_for_member(db, task_id, user)
    require_task_editor(db, task, board, user)
    changes = data.model_dump(exclude_unset=True)  # chỉ lấy trường người dùng thực sự gửi

    if "title" in changes:
        if not changes["title"] or not changes["title"].strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tiêu đề không được để trống")
        changes["title"] = changes["title"].strip()
    if "priority" in changes and changes["priority"] is None:
        changes.pop("priority")

    # F20: người làm là MỘT trong hai — tài khoản (assignee_id) hoặc tên chữ (assignee_name)
    name_before = task.assignee_name
    if "assignee_name" in changes:
        changes["assignee_name"] = _clean_name(changes["assignee_name"])
        if changes["assignee_name"]:
            changes["assignee_id"] = None
    if changes.get("assignee_id") is not None:
        changes["assignee_name"] = None

    assignee_changed = "assignee_id" in changes and changes["assignee_id"] != task.assignee_id
    if assignee_changed:
        ensure_member_user(db, board.workspace_id, changes["assignee_id"])

    for field, value in changes.items():
        setattr(task, field, value)
    db.flush()
    if assignee_changed:
        db.refresh(task)
        notify_assigned(db, task, board, user)
    db.commit()
    db.refresh(task)
    board_changed(background, board.id, user.id)
    if task.assignee_name != name_before:
        _names_changed(board)
    return _task_detail(db, task)


@router.post("/tasks/{task_id}/move", response_model=TaskOut)
def move_task(task_id: int, data: TaskMove, user: CurrentUser, db: DB, background: BackgroundTasks):
    """Kéo-thả. Server tự tính vị trí mới → client chỉ cần gửi cột đích và thứ tự."""
    task, board = get_task_for_member(db, task_id, user)
    require_task_editor(db, task, board, user)
    _column_of_board(db, data.column_id, board.id)
    task.position = position_at_index(db, data.column_id, data.index, exclude_task_id=task.id)
    task.column_id = data.column_id
    db.commit()
    db.refresh(task)
    board_changed(background, board.id, user.id)
    return task


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, user: CurrentUser, db: DB, background: BackgroundTasks):
    task, board = get_task_for_member(db, task_id, user)
    require_task_editor(db, task, board, user)
    had_name = bool(task.assignee_name)
    db.delete(task)
    db.commit()
    board_changed(background, board.id, user.id)
    if had_name:
        _names_changed(board)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Bình luận ----------


@router.post("/tasks/{task_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(task_id: int, data: CommentCreate, user: CurrentUser, db: DB, background: BackgroundTasks):
    task, board = get_task_for_member(db, task_id, user)
    c = TaskComment(task_id=task.id, user_id=user.id, content=data.content.strip())
    db.add(c)
    db.commit()
    db.refresh(c)
    board_changed(background, board.id, user.id)
    return c


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: int, user: CurrentUser, db: DB, background: BackgroundTasks):
    c = db.get(TaskComment, comment_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy bình luận")
    _, board = get_task_for_member(db, c.task_id, user)
    if c.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ xóa được bình luận của mình")
    db.delete(c)
    db.commit()
    board_changed(background, board.id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Việc của tôi ----------


@router.get("/me/tasks", response_model=list[MyTaskOut])
def my_tasks(user: CurrentUser, db: DB, include_done: bool = False):
    """Mọi việc được giao cho tôi, ở mọi nhóm tôi đang tham gia."""
    q = (
        select(Task, Board, Workspace, BoardColumn)
        .join(Board, Task.board_id == Board.id)
        .join(Workspace, Board.workspace_id == Workspace.id)
        .join(BoardColumn, Task.column_id == BoardColumn.id)
        .join(
            WorkspaceMember,
            (WorkspaceMember.workspace_id == Workspace.id) & (WorkspaceMember.user_id == user.id),
        )
        .where(Task.assignee_id == user.id)
        .order_by(Task.due_date.asc().nulls_last(), Task.id)
    )
    if not include_done:
        q = q.where(BoardColumn.is_done.is_(False))
    out: list[MyTaskOut] = []
    for task, board, ws, col in db.execute(q).unique().all():
        base = TaskOut.model_validate(task).model_dump()
        out.append(
            MyTaskOut(
                **base,
                board_name=board.name,
                workspace_id=ws.id,
                workspace_name=ws.name,
                column_name=col.name,
                is_done=col.is_done,
            )
        )
    return out
