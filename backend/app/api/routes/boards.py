"""F04: bảng và cột Kanban."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, get_board_for_member, get_column_for_member, get_membership
from app.core.realtime import board_room, manager
from app.models import Board, BoardColumn, Task, TaskComment, Workspace, WorkspaceMember
from app.schemas.board import (
    BoardCreate,
    BoardDetail,
    BoardUpdate,
    ColumnCreate,
    ColumnOut,
    ColumnUpdate,
    TaskOut,
)
from app.schemas.common import UserBrief
from app.schemas.workspace import BoardBrief
from app.services.board_service import create_board_with_default_columns, next_column_position

router = APIRouter(tags=["boards"])


def board_changed(background: BackgroundTasks, board_id: int, user_id: int, kind: str = "board_updated") -> None:
    """Sau khi trả response, báo cho mọi người đang mở bảng biết để tải lại."""
    background.add_task(manager.broadcast, board_room(board_id), {"type": kind, "board_id": board_id, "by": user_id})


def build_board_detail(db: DB, board: Board) -> BoardDetail:
    tasks = db.scalars(select(Task).where(Task.board_id == board.id).order_by(Task.position, Task.id)).unique().all()
    counts = dict(
        db.execute(
            select(TaskComment.task_id, func.count())
            .join(Task, Task.id == TaskComment.task_id)
            .where(Task.board_id == board.id)
            .group_by(TaskComment.task_id)
        ).all()
    )
    by_col: dict[int, list[TaskOut]] = {c.id: [] for c in board.columns}
    for t in tasks:
        out = TaskOut.model_validate(t)
        out.comment_count = counts.get(t.id, 0)
        by_col.setdefault(t.column_id, []).append(out)

    members = db.scalars(
        select(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == board.workspace_id)
        .order_by(WorkspaceMember.joined_at)
    ).all()
    ws = db.get(Workspace, board.workspace_id)
    return BoardDetail(
        id=board.id,
        workspace_id=board.workspace_id,
        workspace_name=ws.name if ws else "",
        owner_id=ws.owner_id if ws else None,
        name=board.name,
        columns=[
            ColumnOut(id=c.id, name=c.name, position=c.position, is_done=c.is_done, tasks=by_col[c.id])
            for c in board.columns
        ],
        members=[UserBrief.model_validate(m.user) for m in members],
    )


# ---------- Bảng ----------


@router.get("/workspaces/{workspace_id}/boards", response_model=list[BoardBrief])
def list_boards(workspace_id: int, user: CurrentUser, db: DB):
    get_membership(db, workspace_id, user)
    return db.scalars(select(Board).where(Board.workspace_id == workspace_id).order_by(Board.id)).all()


@router.post("/workspaces/{workspace_id}/boards", response_model=BoardBrief, status_code=status.HTTP_201_CREATED)
def create_board(workspace_id: int, data: BoardCreate, user: CurrentUser, db: DB):
    get_membership(db, workspace_id, user)
    board = create_board_with_default_columns(db, workspace_id, data.name.strip())
    db.commit()
    return board


@router.get("/boards/{board_id}", response_model=BoardDetail)
def get_board(board_id: int, user: CurrentUser, db: DB):
    board = get_board_for_member(db, board_id, user)
    return build_board_detail(db, board)


@router.patch("/boards/{board_id}", response_model=BoardBrief)
def rename_board(board_id: int, data: BoardUpdate, user: CurrentUser, db: DB, background: BackgroundTasks):
    board = get_board_for_member(db, board_id, user)
    board.name = data.name.strip()
    db.commit()
    board_changed(background, board.id, user.id)
    return board


@router.delete("/boards/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_board(board_id: int, user: CurrentUser, db: DB, background: BackgroundTasks):
    board = get_board_for_member(db, board_id, user)
    db.delete(board)
    db.commit()
    board_changed(background, board_id, user.id, "board_deleted")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Cột ----------


@router.post("/boards/{board_id}/columns", response_model=ColumnOut, status_code=status.HTTP_201_CREATED)
def create_column(board_id: int, data: ColumnCreate, user: CurrentUser, db: DB, background: BackgroundTasks):
    board = get_board_for_member(db, board_id, user)
    col = BoardColumn(
        board_id=board.id, name=data.name.strip(), is_done=data.is_done, position=next_column_position(db, board.id)
    )
    db.add(col)
    db.commit()
    board_changed(background, board.id, user.id)
    return ColumnOut(id=col.id, name=col.name, position=col.position, is_done=col.is_done, tasks=[])


@router.patch("/columns/{column_id}", response_model=ColumnOut)
def update_column(column_id: int, data: ColumnUpdate, user: CurrentUser, db: DB, background: BackgroundTasks):
    col = get_column_for_member(db, column_id, user)
    if data.name is not None:
        col.name = data.name.strip()
    if data.is_done is not None:
        col.is_done = data.is_done
    db.commit()
    board_changed(background, col.board_id, user.id)
    return ColumnOut(id=col.id, name=col.name, position=col.position, is_done=col.is_done, tasks=[])


@router.delete("/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_column(column_id: int, user: CurrentUser, db: DB, background: BackgroundTasks):
    col = get_column_for_member(db, column_id, user)
    n_cols = db.scalar(select(func.count()).where(BoardColumn.board_id == col.board_id))
    if n_cols <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bảng phải còn ít nhất 1 cột")
    board_id = col.board_id
    db.delete(col)  # các thẻ trong cột bị xóa theo (ON DELETE CASCADE)
    db.commit()
    board_changed(background, board_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
