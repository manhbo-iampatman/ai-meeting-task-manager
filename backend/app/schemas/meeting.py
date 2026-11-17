from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, UserBrief


class SegmentIn(BaseModel):
    start: float | None = None
    end: float | None = None
    text: str = Field(max_length=5000)


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


class MeetingDetail(MeetingOut):
    has_audio: bool = False
    transcript: TranscriptOut | None = None
    summary: SummaryOut | None = None
    extracted_tasks: list[ExtractedTaskOut] = []
