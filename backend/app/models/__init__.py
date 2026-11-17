"""Import mọi model ở đây để Alembic và SQLAlchemy "thấy" đủ các bảng."""

from app.models.board import Board, BoardColumn, Task, TaskComment
from app.models.meeting import Meeting, MeetingStatus, Transcript
from app.models.notification import Notification
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

__all__ = ["Meeting", "MeetingStatus", "Transcript", "User", "Workspace", "WorkspaceMember", "Board", "BoardColumn", "Task", "TaskComment", "Notification"]
