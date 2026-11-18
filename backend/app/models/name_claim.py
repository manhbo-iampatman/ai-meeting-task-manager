"""F21 — Tự nhận tên: một thành viên bấm "Đây là tôi" cho một tên chưa có người nhận."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import User


class NameClaim(Base):
    """Nhật ký một lần nhận tên. Lưu đủ để trưởng nhóm HOÀN TÁC đúng những gì đã đổi."""

    __tablename__ = "name_claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))  # tên hiển thị, vd. "Su"
    name_key: Mapped[str] = mapped_column(String(100))  # dạng chuẩn hóa để gộp: "su"
    task_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)  # thẻ trên bảng đã chuyển cho người nhận
    draft_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)  # đầu việc nháp đã ghép cho người nhận
    added_nickname: Mapped[str | None] = mapped_column(String(50))  # biệt danh được thêm (None = đã có sẵn)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
