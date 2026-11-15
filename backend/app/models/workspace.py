from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.user import User


class Workspace(TimestampMixin, Base):
    """Nhóm làm việc. Mỗi nhóm có nhiều thành viên và nhiều bảng."""

    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Mã mời: ai có link /join/<mã> thì vào được nhóm
    invite_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", passive_deletes=True
    )


class WorkspaceMember(Base):
    """Bảng trung gian nhiều-nhiều giữa User và Workspace, kèm vai trò và biệt danh."""

    __tablename__ = "workspace_members"

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # owner | member
    # Biệt danh: "Nam", "anh Nam", "Nam béo"... Giai đoạn 4 dùng để AI ghép tên trong cuộc họp
    nicknames: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(lazy="joined")
