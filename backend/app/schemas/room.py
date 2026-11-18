from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, UserBrief


class RoomCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class RoomOut(ORMModel):
    """Thông tin một phòng Online Meeting."""

    code: str
    workspace_id: int
    title: str
    status: str  # open | ended
    host: UserBrief | None
    owner_id: int | None = None  # trưởng nhóm (để hiện nhãn trong danh sách người tham gia)
    recording: str  # idle | on | stopped
    recording_started_at: datetime | None
    meeting_id: int | None  # cuộc họp sinh ra sau khi phòng kết thúc (nếu có ghi âm)
    created_at: datetime
    # --- theo người đang xem ---
    workspace_name: str = ""
    is_member: bool = False
    is_host: bool = False
    can_control: bool = False  # được bắt đầu / dừng ghi, kết thúc phòng (chủ phòng + trưởng nhóm)


class RoomJoinOut(BaseModel):
    room: RoomOut
    token: str  # vé LiveKit
    joined_workspace: bool = False  # vừa được tự thêm vào nhóm nhờ link phòng


class RoomEndOut(BaseModel):
    room: RoomOut
    meeting_id: int | None  # None = buổi họp không ghi âm → không tạo cuộc họp


class TrackCreate(BaseModel):
    mime: str = Field(default="audio/webm", max_length=100)
    elapsed_ms: int = Field(default=0, ge=0)  # máy ghi của trình duyệt đã chạy được bao lâu


class TrackOut(BaseModel):
    track_id: int
    next_seq: int


class MeetingTrackOut(BaseModel):
    """Ghi âm của một người trong cuộc họp Online Meeting (hiện ở trang cuộc họp)."""

    id: int
    user_id: int | None
    speaker_name: str
    finished: bool  # trình duyệt đã gửi hết chưa
    has_audio: bool
    merged: bool  # lời của người này đã nằm trong bản ghi chưa
    pending: bool  # có ghi âm đến muộn đang chờ người duyệt bấm "Bổ sung"
