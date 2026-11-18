"""F21 — Tự nhận tên.

Trong họp người ta gọi nhau bằng biệt danh, tên thân mật, tên giả ("Su", "anh Hai"). Máy
không thể biết "Su" là tài khoản nào, nhưng chính người đó thì biết. Nên:

  1. Tên AI nghe được (hoặc người dùng gõ tay) mà chưa khớp tài khoản → thẻ / đầu việc nháp
     mang TÊN CHỮ (F20). Các tên đó gom thành danh sách "tên chưa có người nhận".
  2. Một thành viên bấm "Đây là tôi" → mọi thẻ + đầu việc nháp mang tên đó chuyển cho họ,
     tên được lưu thành BIỆT DANH của họ → cuộc họp sau AI tự ghép đúng.
  3. Có hiệu lực NGAY. Trưởng nhóm nhận thông báo và có thể HOÀN TÁC (nhận nhầm / nhận bậy).

Gom tên: "Lan", "lan", "chị Lan" là một (bỏ xưng hô, không phân biệt hoa thường), nhưng
vẫn phân biệt dấu ("Năm" ≠ "Nam") — xem `name_key`.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.postprocess.name_matching import MemberInfo, display_name, match_name, name_key
from app.models import (
    Board,
    ExtractedTask,
    ExtractedTaskStatus,
    Meeting,
    NameClaim,
    Notification,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)

# Ghép tên ở mức này trở lên thì gợi ý "Bạn có phải là … không?" (vẫn phải tự bấm nhận)
SUGGEST_METHODS = {"exact", "no_accent", "fuzzy"}


@dataclass
class PendingName:
    key: str
    variants: Counter = field(default_factory=Counter)  # các cách viết đã gặp → số lần
    tasks: list[tuple[Task, Board]] = field(default_factory=list)
    drafts: list[tuple[ExtractedTask, Meeting]] = field(default_factory=list)

    @property
    def name(self) -> str:
        """Cách viết hay gặp nhất, đã bỏ xưng hô: "chị Lan" ×1, "Lan" ×3 → "Lan"."""
        return self.variants.most_common(1)[0][0]


def collect_pending(db: Session, workspace_id: int) -> dict[str, PendingName]:
    """Mọi tên chữ chưa có người nhận trong nhóm: trên thẻ (mọi bảng) + đầu việc nháp chưa đẩy."""
    out: dict[str, PendingName] = {}

    def add(raw: str) -> PendingName | None:
        key = name_key(raw)
        if not key:
            return None
        p = out.setdefault(key, PendingName(key))
        p.variants[display_name(raw)] += 1
        return p

    tasks = db.execute(
        select(Task, Board)
        .join(Board, Task.board_id == Board.id)
        .where(Board.workspace_id == workspace_id, Task.assignee_id.is_(None), Task.assignee_name.is_not(None))
        .order_by(Task.id)
    ).unique().all()
    for t, b in tasks:
        if p := add(t.assignee_name):
            p.tasks.append((t, b))

    drafts = db.execute(
        select(ExtractedTask, Meeting)
        .join(Meeting, ExtractedTask.meeting_id == Meeting.id)
        .where(
            Meeting.workspace_id == workspace_id,
            ExtractedTask.status != ExtractedTaskStatus.ACCEPTED,
            ExtractedTask.assignee_id.is_(None),
            ExtractedTask.assignee_name.is_not(None),
        )
        .order_by(ExtractedTask.id)
    ).unique().all()
    for d, m in drafts:
        if p := add(d.assignee_name):
            p.drafts.append((d, m))
    return out


def is_suggested(pending: PendingName, member: WorkspaceMember) -> bool:
    """Tên đang chờ có giống tên / biệt danh của người đang xem không (dùng lại hàm ghép tên của GĐ4)."""
    me = MemberInfo(member.user_id, member.user.full_name, list(member.nicknames or []))
    return match_name(pending.name, [me]).method in SUGGEST_METHODS


def has_claimed(db: Session, workspace_id: int, user_id: int) -> bool:
    """Người này đã nhận một tên trong nhóm (và chưa bị hoàn tác) → không hiện danh sách nữa."""
    return (
        db.scalar(
            select(NameClaim.id)
            .where(NameClaim.workspace_id == workspace_id, NameClaim.user_id == user_id, NameClaim.undone_at.is_(None))
            .limit(1)
        )
        is not None
    )


def _owners(db: Session, workspace_id: int) -> list[WorkspaceMember]:
    return list(
        db.scalars(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
        )
    )


def claim(db: Session, workspace_id: int, member: WorkspaceMember, key: str) -> tuple[NameClaim, set[int]]:
    """Thành viên `member` nhận tên `key`. Trả về (bản ghi nhận tên, id các bảng bị thay đổi).

    Chỉ `flush`; route commit một lần → nhận tên là một transaction.
    """
    pending = collect_pending(db, workspace_id).get(name_key(key))
    if pending is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tên này không còn chờ nhận (có thể người khác vừa nhận)")
    user = member.user

    for t, _ in pending.tasks:
        t.assignee_id, t.assignee_name = user.id, None
    for d, _ in pending.drafts:
        d.assignee_id, d.assignee_name, d.assignee_match = user.id, None, "claimed"

    # Lưu thành biệt danh → cuộc họp sau AI tự ghép "Su" = người này (nếu chưa có biệt danh tương đương)
    nicknames = list(member.nicknames or [])
    added = None
    if not any(name_key(n) == pending.key for n in nicknames):
        added = pending.name[:50]
        member.nicknames = nicknames + [added]

    c = NameClaim(
        workspace_id=workspace_id,
        user_id=user.id,
        name=pending.name,
        name_key=pending.key,
        task_ids=[t.id for t, _ in pending.tasks],
        draft_ids=[d.id for d, _ in pending.drafts],
        added_nickname=added,
    )
    db.add(c)
    db.flush()

    ws = db.get(Workspace, workspace_id)
    payload = {
        "claim_id": c.id,
        "workspace_id": workspace_id,
        "workspace_name": ws.name if ws else "",
        "name": c.name,
        "task_count": len(c.task_ids),
        "draft_count": len(c.draft_ids),
    }
    # Một thông báo TỔNG cho người nhận (không phải mỗi việc một thông báo)
    db.add(Notification(user_id=user.id, type="name_claimed", payload=payload))
    # Trưởng nhóm được báo, kèm nút Hoàn tác (trừ khi chính trưởng nhóm nhận)
    for o in _owners(db, workspace_id):
        if o.user_id != user.id:
            db.add(
                Notification(
                    user_id=o.user_id,
                    type="name_claimed_member",
                    payload={**payload, "claimer_id": user.id, "claimer_name": user.full_name},
                )
            )
    db.flush()
    return c, {b.id for _, b in pending.tasks}


def undo(db: Session, c: NameClaim, actor: User) -> set[int]:
    """Trưởng nhóm hoàn tác một lần nhận tên. Trả về id các bảng bị thay đổi.

    Chỉ trả lại những gì VẪN đang thuộc người đã nhận (việc đã được giao lại cho người khác
    sau đó thì giữ nguyên).
    """
    if c.undone_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Lần nhận tên này đã được hoàn tác")
    boards: set[int] = set()

    # Thẻ đã chuyển lúc nhận + thẻ được đẩy lên bảng SAU khi nhận từ các đầu việc nháp đã ghép
    drafts = list(db.scalars(select(ExtractedTask).where(ExtractedTask.id.in_(c.draft_ids or [-1]))))
    task_ids = set(c.task_ids or []) | {d.task_id for d in drafts if d.task_id}
    for t in db.scalars(select(Task).where(Task.id.in_(task_ids or {-1}))):
        if t.assignee_id == c.user_id:
            t.assignee_id, t.assignee_name = None, c.name
            boards.add(t.board_id)
    for d in drafts:
        if d.status != ExtractedTaskStatus.ACCEPTED and d.assignee_id == c.user_id:
            d.assignee_id, d.assignee_name, d.assignee_match = None, c.name, "none"

    member = db.get(WorkspaceMember, (c.workspace_id, c.user_id))
    if member is not None and c.added_nickname:
        member.nicknames = [n for n in (member.nicknames or []) if n != c.added_nickname]

    c.undone_at, c.undone_by = datetime.now(timezone.utc), actor.id

    # Đánh dấu "đã hoàn tác" trên thông báo của trưởng nhóm (để nút Hoàn tác biến mất)
    for n in db.scalars(select(Notification).where(Notification.type == "name_claimed_member")):
        if n.payload.get("claim_id") == c.id:
            n.payload = {**n.payload, "undone": True}
    if member is not None:
        db.add(
            Notification(
                user_id=c.user_id,
                type="name_claim_undone",
                payload={"workspace_id": c.workspace_id, "name": c.name, "actor_name": actor.full_name},
            )
        )
    db.flush()
    return boards
