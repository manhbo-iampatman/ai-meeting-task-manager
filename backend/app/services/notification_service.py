"""F08: tạo thông báo khi được giao việc và khi việc sắp đến hạn / quá hạn."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Board, BoardColumn, Notification, Task, User


def notify_assigned(db: Session, task: Task, board: Board, actor: User) -> None:
    """Báo cho người được giao việc (trừ khi tự giao cho chính mình)."""
    if task.assignee_id is None or task.assignee_id == actor.id:
        return
    db.add(
        Notification(
            user_id=task.assignee_id,
            type="task_assigned",
            payload={
                "task_id": task.id,
                "task_title": task.title,
                "board_id": board.id,
                "board_name": board.name,
                "workspace_id": board.workspace_id,
                "actor_name": actor.full_name,
                "due_date": task.due_date.isoformat() if task.due_date else None,
            },
        )
    )


def generate_due_notifications(db: Session, user: User, today: date | None = None) -> None:
    """Sinh thông báo hạn chót cho các việc của user (gọi mỗi khi user xem thông báo).

    Cách "lười" (lazy) này không cần tiến trình chạy định kỳ (cron). Mỗi việc chỉ
    được báo 1 lần cho mỗi loại (sắp hạn / quá hạn) và mỗi hạn chót.
    """
    today = today or date.today()
    rows = db.execute(
        select(Task, Board)
        .join(BoardColumn, Task.column_id == BoardColumn.id)
        .join(Board, Task.board_id == Board.id)
        .where(
            Task.assignee_id == user.id,
            Task.due_date.is_not(None),
            Task.due_date <= today + timedelta(days=1),
            BoardColumn.is_done.is_(False),
        )
    ).all()
    if not rows:
        return

    existing = {
        (n.type, n.payload.get("task_id"), n.payload.get("due_date"))
        for n in db.scalars(
            select(Notification).where(
                Notification.user_id == user.id, Notification.type.in_(["task_due_soon", "task_overdue"])
            )
        )
    }
    for task, board in rows:
        ntype = "task_overdue" if task.due_date < today else "task_due_soon"
        key = (ntype, task.id, task.due_date.isoformat())
        if key in existing:
            continue
        db.add(
            Notification(
                user_id=user.id,
                type=ntype,
                payload={
                    "task_id": task.id,
                    "task_title": task.title,
                    "board_id": board.id,
                    "board_name": board.name,
                    "workspace_id": board.workspace_id,
                    "due_date": task.due_date.isoformat(),
                },
            )
        )
    db.commit()
