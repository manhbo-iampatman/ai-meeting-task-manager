"""F21: danh sách "tên chưa có người nhận" của nhóm, tự nhận tên, trưởng nhóm hoàn tác."""

from datetime import date

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser, get_membership, require_owner
from app.api.routes.boards import board_changed
from app.core.realtime import publish_event, workspace_room
from app.models import NameClaim
from app.services import name_claim_service as svc

router = APIRouter(tags=["names"])


class PendingTaskOut(BaseModel):
    id: int
    title: str
    board_id: int
    board_name: str
    due_date: date | None


class PendingDraftOut(BaseModel):
    id: int
    title: str
    meeting_id: int
    meeting_title: str
    status: str  # pending = chờ duyệt · rejected = đã bỏ lúc đẩy lên bảng


class PendingNameOut(BaseModel):
    key: str  # gửi lại khi bấm nhận
    name: str  # tên hiển thị, vd. "Su"
    variants: list[str]  # các cách viết đã gặp: ["Su", "chị Su"]
    tasks: list[PendingTaskOut]  # thẻ trên bảng
    drafts: list[PendingDraftOut]  # đầu việc nháp ở cuộc họp chưa đẩy
    suggested: bool  # giống tên / biệt danh của người đang xem → gợi ý "Bạn có phải là … không?"


class ClaimIn(BaseModel):
    key: str = Field(min_length=1, max_length=100)


class ClaimOut(BaseModel):
    id: int
    name: str
    task_count: int
    draft_count: int
    added_nickname: str | None


def _claim_out(c: NameClaim) -> ClaimOut:
    return ClaimOut(
        id=c.id, name=c.name, task_count=len(c.task_ids), draft_count=len(c.draft_ids), added_nickname=c.added_nickname
    )


def _changed(background: BackgroundTasks, workspace_id: int, board_ids: set[int], user_id: int) -> None:
    for b in board_ids:
        board_changed(background, b, user_id)
    publish_event(workspace_room(workspace_id), {"type": "names_updated"})


@router.get("/workspaces/{workspace_id}/pending-names", response_model=list[PendingNameOut])
def list_pending_names(workspace_id: int, user: CurrentUser, db: DB):
    """Mọi thành viên CHƯA nhận tên đều xem được (người mới vào nhóm, và cả thành viên cũ bị gọi
    bằng biệt danh lạ). Đã nhận một tên (chưa bị hoàn tác) thì danh sách ẩn đi — quyết định 18/11/2026."""
    me = get_membership(db, workspace_id, user)
    if svc.has_claimed(db, workspace_id, user.id):
        return []
    pending = svc.collect_pending(db, workspace_id).values()
    out = [
        PendingNameOut(
            key=p.key,
            name=p.name,
            variants=[v for v, _ in p.variants.most_common()],
            tasks=[PendingTaskOut(id=t.id, title=t.title, board_id=b.id, board_name=b.name, due_date=t.due_date) for t, b in p.tasks],
            drafts=[
                PendingDraftOut(id=d.id, title=d.title, meeting_id=m.id, meeting_title=m.title, status=d.status)
                for d, m in p.drafts
            ],
            suggested=svc.is_suggested(p, me),
        )
        for p in pending
    ]
    # Tên được gợi ý cho mình lên đầu, còn lại theo số việc
    return sorted(out, key=lambda x: (not x.suggested, -(len(x.tasks) + len(x.drafts)), x.name.lower()))


@router.post("/workspaces/{workspace_id}/pending-names/claim", response_model=ClaimOut)
def claim_name(workspace_id: int, data: ClaimIn, user: CurrentUser, db: DB, background: BackgroundTasks):
    """Bấm "Đây là tôi": có hiệu lực ngay; trưởng nhóm được báo và có thể hoàn tác."""
    me = get_membership(db, workspace_id, user)
    c, boards = svc.claim(db, workspace_id, me, data.key)
    db.commit()
    _changed(background, workspace_id, boards, user.id)
    return _claim_out(c)


@router.post("/name-claims/{claim_id}/undo", response_model=ClaimOut)
def undo_claim(claim_id: int, user: CurrentUser, db: DB, background: BackgroundTasks):
    """Trưởng nhóm hoàn tác: việc trở lại mang tên chữ, biệt danh vừa thêm bị gỡ."""
    c = db.get(NameClaim, claim_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy lần nhận tên này")
    require_owner(get_membership(db, c.workspace_id, user))
    boards = svc.undo(db, c, user)
    db.commit()
    _changed(background, c.workspace_id, boards, user.id)
    return _claim_out(c)
