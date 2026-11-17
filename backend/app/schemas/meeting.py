from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


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
    audio_filename: str | None
    audio_size: int | None
    created_by: int | None
    created_at: datetime
    duration_sec: float | None = None


class MeetingDetail(MeetingOut):
    has_audio: bool = False
    transcript: TranscriptOut | None = None
