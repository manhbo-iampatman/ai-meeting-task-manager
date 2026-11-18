"""Nghiệp vụ về bảng và thứ tự thẻ."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Board, BoardColumn, Task

DEFAULT_COLUMNS = [("Cần làm", False), ("Đang làm", False), ("Chờ duyệt", False), ("Hoàn thành", True)]

POSITION_GAP = 1000.0
MIN_GAP = 1e-6


def create_board_with_default_columns(db: Session, workspace_id: int, name: str) -> Board:
    board = Board(workspace_id=workspace_id, name=name)
    board.columns = [BoardColumn(name=n, position=i, is_done=done) for i, (n, done) in enumerate(DEFAULT_COLUMNS)]
    db.add(board)
    db.flush()
    return board


def _sibling_positions(db: Session, column_id: int, exclude_task_id: int | None) -> list[float]:
    q = select(Task.position).where(Task.column_id == column_id)
    if exclude_task_id is not None:
        q = q.where(Task.id != exclude_task_id)
    return list(db.scalars(q.order_by(Task.position, Task.id)))


def _rebalance(db: Session, column_id: int, exclude_task_id: int | None) -> None:
    """Đánh số lại cả cột: 1000, 2000, 3000... (hiếm khi cần)."""
    q = select(Task).where(Task.column_id == column_id)
    if exclude_task_id is not None:
        q = q.where(Task.id != exclude_task_id)
    for i, t in enumerate(db.scalars(q.order_by(Task.position, Task.id)), start=1):
        t.position = i * POSITION_GAP
    db.flush()


def position_at_index(db: Session, column_id: int, index: int, exclude_task_id: int | None = None) -> float:
    """Tính vị trí (số thực) để đặt thẻ vào chỗ thứ `index` trong cột.

    Kỹ thuật "fractional indexing": vị trí mới = trung bình cộng của 2 thẻ kề bên.
    Ví dụ chèn giữa 1000 và 2000 → 1500. Chỉ phải cập nhật ĐÚNG 1 thẻ đang kéo,
    không phải đánh số lại cả cột. Khi khoảng cách quá nhỏ thì đánh số lại (rebalance).
    """
    siblings = _sibling_positions(db, column_id, exclude_task_id)
    index = max(0, min(index, len(siblings)))
    before = siblings[index - 1] if index > 0 else None
    after = siblings[index] if index < len(siblings) else None

    if before is not None and after is not None and after - before < MIN_GAP:
        _rebalance(db, column_id, exclude_task_id)
        return position_at_index(db, column_id, index, exclude_task_id)

    if before is None and after is None:
        return POSITION_GAP
    if before is None:
        return after - POSITION_GAP
    if after is None:
        return before + POSITION_GAP
    return (before + after) / 2


def next_column_position(db: Session, board_id: int) -> int:
    current = db.scalar(select(func.max(BoardColumn.position)).where(BoardColumn.board_id == board_id))
    return 0 if current is None else current + 1
