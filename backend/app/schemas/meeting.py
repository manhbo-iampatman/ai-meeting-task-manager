from datetime import date, datetime

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_serializer

from app.schemas.common import ORMModel, UserBrief
from app.schemas.room import MeetingTrackOut


class SegmentIn(BaseModel):
    start: float | None = None
    end: float | None = None
    text: str = Field(max_length=5000)
    # Online Meeting: ai nói câu này. Giữ nguyên khi người dùng sửa chữ trong bản ghi.
    speaker: str | None = Field(default=None, max_length=100)
    speaker_id: int | None = None
    track_id: int | None = None
    rms: float | None = None  # âm lượng (để lọc tiếng vọng)

    @model_serializer(mode="wrap")
    def _hide_empty_speaker_fields(self, handler):
        """Cuộc họp thường (không phải Online Meeting) không có các trường người nói → không
        trả về / không lưu các khóa rỗng đó."""
        data = handler(self)
        for k in ("speaker", "speaker_id", "track_id", "rms"):
            if data.get(k) is None:
                data.pop(k, None)
        return data


class TranscriptUpdate(BaseModel):
    segments: list[SegmentIn] = Field(max_length=20000)


class TranscriptOut(ORMModel):
    full_text: str
    segments: list[SegmentIn]
    language: str | None
    stt_model: str | None
    duration_sec: float | None
    processing_sec: float | None
    edited: bool
    updated_at: datetime


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    meeting_date: date | None = None


class MeetingOut(ORMModel):
    id: int
    workspace_id: int
    title: str
    meeting_date: date
    source_type: str
    status: str
    progress: int
    error: str | None
    status_note: str | None = None  # thông báo phụ trong lúc xử lý (vd. đã chuyển sang mô hình dự phòng)
    audio_filename: str | None
    audio_size: int | None
    created_by: int | None
    created_at: datetime
    duration_sec: float | None = None


class SummaryOut(BaseModel):
    """Biên bản do AI viết (F13)."""

    topic: str = ""
    key_points: list[str] = []
    decisions: list[str] = []
    open_issues: list[str] = []
    llm_model: str | None = None
    # Mô hình chính đã bị bỏ qua vì quá tải → biên bản do mô hình dự phòng (llm_model) viết
    fallback_from: str | None = None
    chunk_count: int = 1
    processing_sec: float | None = None
    created_at: datetime
    # True = bản ghi đã bị sửa SAU khi tóm tắt → biên bản có thể không còn khớp, nên tóm tắt lại
    stale: bool = False


class ExtractedTaskOut(ORMModel):
    """Đầu việc nháp do AI trích xuất (F14–F16)."""

    id: int
    position: int
    title: str
    raw_assignee: str | None
    assignee: UserBrief | None
    assignee_match: str
    assignee_score: int
    assignee_candidates: list[int]
    due_text: str | None
    due_date: date | None
    due_approximate: bool
    priority: str
    evidence_quote: str
    evidence_found: bool
    evidence_segment: int | None
    evidence_start: float | None
    status: str
    # --- Duyệt (Giai đoạn 5) ---
    assignee_name: str | None  # F20: tên dạng chữ khi chưa có tài khoản
    selected: bool  # có tick "đưa lên bảng" không
    task_id: int | None  # thẻ đã tạo trên bảng (khi status = accepted)
    task_board_id: int | None = None  # bảng chứa thẻ đó (để mở thẻ)
    duplicate_of_task_id: int | None  # giống một thẻ đã đẩy từ cuộc họp này


class ExtractedTaskUpdate(BaseModel):
    """Người duyệt sửa đầu việc nháp. Chỉ trường được gửi lên mới bị sửa.

    Người làm: gửi `assignee_id` (thành viên) HOẶC `assignee_name` (tên chữ, F20); gửi cả hai
    là null = chưa có người làm.
    """

    title: str | None = Field(default=None, min_length=1, max_length=255)
    assignee_id: int | None = None
    assignee_name: str | None = Field(default=None, max_length=100)
    due_date: date | None = None
    priority: Literal["low", "medium", "high"] | None = None
    selected: bool | None = None

    @field_validator("title", "assignee_name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else None


class PushIn(BaseModel):
    board_id: int


class MeetingDetail(MeetingOut):
    has_audio: bool = False
    transcript: TranscriptOut | None = None
    summary: SummaryOut | None = None
    extracted_tasks: list[ExtractedTaskOut] = []
    can_review: bool = False  # người đang xem có được duyệt + đẩy lên bảng không
    # Online Meeting: ghi âm của từng người (ai chưa gửi đủ, ai có phần đến muộn chờ bổ sung)
    tracks: list[MeetingTrackOut] = []


class AudioTicketOut(BaseModel):
    """Link nghe lại ghi âm, đã kèm "vé" chỉ dùng được cho file này (xem get_audio_ticket)."""

    url: str
