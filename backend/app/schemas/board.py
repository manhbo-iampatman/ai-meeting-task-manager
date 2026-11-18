from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, UserBrief

Priority = Literal["low", "medium", "high"]


# ---------- Bảng & cột ----------


class BoardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class BoardUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ColumnCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    is_done: bool = False


class ColumnUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    is_done: bool | None = None


# ---------- Công việc ----------


class TaskCreate(BaseModel):
    column_id: int
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    assignee_id: int | None = None
    # F20: giao theo tên khi người đó chưa có tài khoản. Bị bỏ qua nếu đã có assignee_id.
    assignee_name: str | None = Field(default=None, max_length=100)
    due_date: date | None = None
    priority: Priority = "medium"


class TaskUpdate(BaseModel):
    """Chỉ những trường được gửi lên mới bị sửa (dùng exclude_unset)."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    assignee_id: int | None = None
    assignee_name: str | None = Field(default=None, max_length=100)  # F20
    due_date: date | None = None
    priority: Priority | None = None


class TaskMove(BaseModel):
    """Kéo-thả: chuyển thẻ sang cột `column_id`, đặt ở vị trí thứ `index` (0 = đầu cột)."""

    column_id: int
    index: int = Field(ge=0)


class TaskOut(ORMModel):
    id: int
    board_id: int
    column_id: int
    title: str
    description: str | None
    assignee: UserBrief | None
    assignee_name: str | None = None  # F20: người làm chưa có tài khoản
    meeting_id: int | None = None  # F18: thẻ tạo từ cuộc họp nào
    due_date: date | None
    priority: str
    position: float
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    comment_count: int = 0


class ColumnOut(ORMModel):
    id: int
    name: str
    position: int
    is_done: bool
    tasks: list[TaskOut] = []


class BoardDetail(BaseModel):
    id: int
    workspace_id: int
    workspace_name: str
    owner_id: int | None = None  # trưởng nhóm — được kéo / sửa / xóa mọi thẻ
    name: str
    columns: list[ColumnOut]
    members: list[UserBrief]


# ---------- Bình luận ----------


class CommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class CommentOut(ORMModel):
    id: int
    task_id: int
    user: UserBrief
    content: str
    created_at: datetime


class TaskSource(BaseModel):
    """F18: thẻ này sinh ra từ cuộc họp nào, từ câu nói nào."""

    meeting_id: int
    meeting_title: str
    meeting_date: date
    evidence_quote: str | None = None
    evidence_start: float | None = None  # giây trong ghi âm → bấm nghe lại


class TaskDetail(TaskOut):
    comments: list[CommentOut] = []
    column_name: str = ""
    source: TaskSource | None = None


class MyTaskOut(TaskOut):
    """Một việc trong danh sách "Việc của tôi" (kèm tên bảng, nhóm, cột)."""

    board_name: str
    workspace_id: int
    workspace_name: str
    column_name: str
    is_done: bool
