from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class MeetingStatus:
    """Vòng đời của một cuộc họp trong hệ thống.

    uploaded ──► queued ──► transcribing ──► transcribed ──► (GĐ4) summarizing ──► review ──► done
                                   │
                                   └──► failed (lỗi: file hỏng, hết bộ nhớ GPU...) → có thể "Thử lại"
    Nếu người dùng dán sẵn văn bản thì đi thẳng tới `transcribed`.
    """

    UPLOADED = "uploaded"
    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    FAILED = "failed"

    PROCESSING = {QUEUED, TRANSCRIBING}


class Meeting(TimestampMixin, Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    meeting_date: Mapped[date] = mapped_column(Date)
    source_type: Mapped[str] = mapped_column(String(10))  # audio (tải file) | recording (ghi trực tiếp) | text

    # Thông tin file ghi âm (nếu có). File lưu trên đĩa, CSDL chỉ lưu đường dẫn.
    audio_path: Mapped[str | None] = mapped_column(String(500))
    audio_filename: Mapped[str | None] = mapped_column(String(255))
    audio_size: Mapped[int | None] = mapped_column(BigInteger)
    audio_mime: Mapped[str | None] = mapped_column(String(100))

    status: Mapped[str] = mapped_column(String(20), default=MeetingStatus.UPLOADED, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0–100 (%)
    error: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(String(64))

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="meeting", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )


class Transcript(Base):
    """Bản ghi văn bản của cuộc họp, chia thành các đoạn (segment) có mốc thời gian."""

    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), unique=True)
    full_text: Mapped[str] = mapped_column(Text, default="")
    # [{"start": 0.0, "end": 3.5, "text": "..."}] — JSONB vì số đoạn thay đổi, không cần bảng riêng
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    language: Mapped[str | None] = mapped_column(String(10))
    stt_model: Mapped[str | None] = mapped_column(String(100))
    duration_sec: Mapped[float | None] = mapped_column(Float)
    processing_sec: Mapped[float | None] = mapped_column(Float)
    # Người dùng đã sửa tay bản ghi chưa (dùng khi đánh giá WER ở chương thực nghiệm)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    meeting: Mapped[Meeting] = relationship(back_populates="transcript")
