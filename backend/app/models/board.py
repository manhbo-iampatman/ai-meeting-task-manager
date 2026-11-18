from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.user import User


class Board(TimestampMixin, Base):
    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))

    columns: Mapped[list["BoardColumn"]] = relationship(
        back_populates="board", order_by="BoardColumn.position", cascade="all, delete-orphan", passive_deletes=True
    )


class BoardColumn(Base):
    """Một cột trên bảng Kanban: Cần làm / Đang làm / Hoàn thành."""

    __tablename__ = "columns"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Cột "hoàn thành": task nằm ở đây không bị nhắc hạn chót nữa
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    board: Mapped[Board] = relationship(back_populates="columns")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    column_id: Mapped[int] = mapped_column(ForeignKey("columns.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    # F20: giao theo TÊN khi người đó chưa có tài khoản ("Duy", "Su"...). Chỉ dùng khi assignee_id trống.
    # Người đó vào nhóm rồi bấm nhận tên (F21) → chuyển sang assignee_id.
    assignee_name: Mapped[str | None] = mapped_column(String(100))
    # F18: thẻ được tạo từ cuộc họp nào (None = tạo tay trên bảng)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(10), default="medium")  # low | medium | high
    # Thứ tự trong cột, dùng số thực để chèn vào giữa 2 thẻ mà không phải đánh số lại cả cột
    position: Mapped[float] = mapped_column(Float, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="joined")


class TaskComment(TimestampMixin, Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)

    user: Mapped[User] = relationship(lazy="joined")
