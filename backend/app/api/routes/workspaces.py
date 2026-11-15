"""F03: nhóm làm việc, thành viên, mời vào nhóm."""

import secrets

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select, update

from app.api.deps import DB, CurrentUser, get_membership, require_owner
from app.models import Board, Task, User, Workspace, WorkspaceMember
from app.schemas.workspace import (
    AddMemberIn,
    BoardBrief,
    JoinIn,
    MemberOut,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceDetail,
    WorkspaceSummary,
    WorkspaceUpdate,
)
from app.services.board_service import create_board_with_default_columns

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _new_invite_code() -> str:
    return secrets.token_urlsafe(9)  # 12 ký tự ngẫu nhiên, khó đoán


def _detail(db: DB, ws: Workspace, my_role: str) -> WorkspaceDetail:
    members = db.scalars(
        select(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == ws.id)
        .order_by(WorkspaceMember.joined_at)
    ).all()
    boards = db.scalars(select(Board).where(Board.workspace_id == ws.id).order_by(Board.id)).all()
    return WorkspaceDetail(
        id=ws.id,
        name=ws.name,
        owner_id=ws.owner_id,
        invite_code=ws.invite_code,
        my_role=my_role,
        members=[MemberOut.model_validate(m) for m in members],
        boards=[BoardBrief.model_validate(b) for b in boards],
    )


@router.get("", response_model=list[WorkspaceSummary])
def list_my_workspaces(user: CurrentUser, db: DB):
    member_count = (
        select(func.count()).where(WorkspaceMember.workspace_id == Workspace.id).correlate(Workspace).scalar_subquery()
    )
    board_count = select(func.count()).where(Board.workspace_id == Workspace.id).correlate(Workspace).scalar_subquery()
    rows = db.execute(
        select(Workspace, WorkspaceMember.role, member_count, board_count)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.created_at)
    ).all()
    return [
        WorkspaceSummary(id=ws.id, name=ws.name, my_role=role, member_count=mc, board_count=bc)
        for ws, role, mc, bc in rows
    ]


@router.post("", response_model=WorkspaceDetail, status_code=status.HTTP_201_CREATED)
def create_workspace(data: WorkspaceCreate, user: CurrentUser, db: DB):
    ws = Workspace(name=data.name.strip(), owner_id=user.id, invite_code=_new_invite_code())
    db.add(ws)
    db.flush()  # để có ws.id
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner", nicknames=[]))
    create_board_with_default_columns(db, ws.id, "Bảng chính")
    db.commit()
    return _detail(db, ws, "owner")


@router.get("/{workspace_id}", response_model=WorkspaceDetail)
def get_workspace(workspace_id: int, user: CurrentUser, db: DB):
    m = get_membership(db, workspace_id, user)
    return _detail(db, m.workspace, m.role)


@router.patch("/{workspace_id}", response_model=WorkspaceDetail)
def rename_workspace(workspace_id: int, data: WorkspaceUpdate, user: CurrentUser, db: DB):
    m = get_membership(db, workspace_id, user)
    require_owner(m)
    m.workspace.name = data.name.strip()
    db.commit()
    return _detail(db, m.workspace, m.role)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: int, user: CurrentUser, db: DB):
    m = get_membership(db, workspace_id, user)
    require_owner(m)
    db.delete(m.workspace)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workspace_id}/invite-code", response_model=WorkspaceDetail)
def regenerate_invite_code(workspace_id: int, user: CurrentUser, db: DB):
    """Đổi mã mời — link cũ hết hiệu lực (khi lỡ để lộ link)."""
    m = get_membership(db, workspace_id, user)
    require_owner(m)
    m.workspace.invite_code = _new_invite_code()
    db.commit()
    return _detail(db, m.workspace, m.role)


@router.post("/join", response_model=WorkspaceDetail)
def join_by_code(data: JoinIn, user: CurrentUser, db: DB):
    ws = db.scalar(select(Workspace).where(Workspace.invite_code == data.invite_code.strip()))
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mã mời không hợp lệ hoặc đã bị đổi")
    existing = db.get(WorkspaceMember, (ws.id, user.id))
    if existing is None:
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="member", nicknames=[]))
        db.commit()
        return _detail(db, ws, "member")
    return _detail(db, ws, existing.role)


@router.post("/{workspace_id}/members", response_model=WorkspaceDetail, status_code=status.HTTP_201_CREATED)
def add_member_by_email(workspace_id: int, data: AddMemberIn, user: CurrentUser, db: DB):
    """Trưởng nhóm thêm thẳng 1 người ĐÃ có tài khoản bằng email."""
    m = get_membership(db, workspace_id, user)
    require_owner(m)
    target = db.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Email này chưa có tài khoản. Hãy gửi link mời để họ đăng ký rồi tham gia."
        )
    if db.get(WorkspaceMember, (workspace_id, target.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Người này đã ở trong nhóm")
    db.add(WorkspaceMember(workspace_id=workspace_id, user_id=target.id, role="member", nicknames=[]))
    db.commit()
    return _detail(db, m.workspace, m.role)


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberOut)
def update_member(workspace_id: int, user_id: int, data: MemberUpdate, user: CurrentUser, db: DB):
    """Sửa biệt danh: trưởng nhóm sửa cho mọi người, thành viên tự sửa của mình."""
    me = get_membership(db, workspace_id, user)
    if user_id != user.id:
        require_owner(me)
    target = db.get(WorkspaceMember, (workspace_id, user_id))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thành viên")
    target.nicknames = data.nicknames
    db.commit()
    db.refresh(target)
    return target


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(workspace_id: int, user_id: int, user: CurrentUser, db: DB):
    """Trưởng nhóm xóa thành viên, hoặc thành viên tự rời nhóm."""
    me = get_membership(db, workspace_id, user)
    if user_id != user.id:
        require_owner(me)
    target = db.get(WorkspaceMember, (workspace_id, user_id))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thành viên")
    if target.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Trưởng nhóm không thể rời nhóm (hãy xóa nhóm)")
    # Bỏ giao các việc của người này trong nhóm
    board_ids = select(Board.id).where(Board.workspace_id == workspace_id)
    db.execute(
        update(Task).where(Task.board_id.in_(board_ids), Task.assignee_id == user_id).values(assignee_id=None)
    )
    db.delete(target)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
