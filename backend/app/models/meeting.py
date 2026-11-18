from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.user import User


class MeetingStatus:
    """Vòng đời của một cuộc họp trong hệ thống.

    uploaded ──► queued ──► transcribing ──► transcribed ──► summarizing ──► review ──► done
                                   │                 ▲            │                ▲         │
                                   │                 └── lỗi LLM ─┘                └─────────┘
                                   │                                    tóm tắt lại sau khi đã đẩy
                                   └──► failed (lỗi: file hỏng, hết bộ nhớ GPU...) → có thể "Thử lại"
    Nếu người dùng dán sẵn văn bản thì đi thẳng tới `transcribed`.

    - summarizing: LLM đang đọc bản ghi để tóm tắt và tách đầu việc (Giai đoạn 4).
    - review: đã có biên bản + đầu việc NHÁP, chờ người dùng duyệt (Giai đoạn 5).
    - done: đã đẩy đầu việc lên bảng. Vẫn tóm tắt lại / đẩy thêm được.
    """

    UPLOADED = "uploaded"
    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    SUMMARIZING = "summarizing"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"

    PROCESSING = {QUEUED, TRANSCRIBING, SUMMARIZING}


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
    # Thông báo phụ trong lúc xử lý, vd. "Mô hình chính quá tải, đã chuyển sang mô hình dự phòng…"
    status_note: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(String(64))

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="meeting", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )
    summary: Mapped["MeetingSummary | None"] = relationship(
        back_populates="meeting", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )
    extracted_tasks: Mapped[list["ExtractedTask"]] = relationship(
        back_populates="meeting", order_by="ExtractedTask.position", cascade="all, delete-orphan", passive_deletes=True
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


class MeetingSummary(Base):
    """Biên bản do LLM viết (F13). Quan hệ 1–1 với cuộc họp; tóm tắt lại thì ghi đè."""

    __tablename__ = "meeting_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), unique=True)
    # {"topic": "...", "key_points": [...], "decisions": [...], "open_issues": [...]}
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    llm_model: Mapped[str | None] = mapped_column(String(100))  # mô hình THỰC SỰ đã viết, vd. "gemini/gemini-3.5-flash"
    # Mô hình chính bị bỏ qua vì quá tải / hết hạn mức → biên bản do mô hình dự phòng viết.
    # None = mô hình chính viết bình thường.
    fallback_from: Mapped[str | None] = mapped_column(String(100))
    chunk_count: Mapped[int] = mapped_column(Integer, default=1)  # bản ghi bị chia mấy đoạn
    processing_sec: Mapped[float | None] = mapped_column(Float)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meeting: Mapped[Meeting] = relationship(back_populates="summary")


class ExtractedTaskStatus:
    PENDING = "pending"  # nháp, chờ duyệt
    ACCEPTED = "accepted"  # đã đẩy lên bảng (thành thẻ `task_id`)
    REJECTED = "rejected"  # bị bỏ tick lúc đẩy — vẫn xem được, tick lại rồi đẩy lần sau


class ExtractedTask(Base):
    """Đầu việc NHÁP do AI trích từ cuộc họp (F14–F16).

    Tách riêng khỏi bảng `tasks`: kết quả AI chỉ là đề xuất, chỉ thành công việc thật
    trên bảng Kanban khi người dùng duyệt (human-in-the-loop, Giai đoạn 5).
    """

    __tablename__ = "extracted_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)  # thứ tự xuất hiện trong cuộc họp
    title: Mapped[str] = mapped_column(String(255))

    # --- Người làm (F15) ---
    raw_assignee: Mapped[str | None] = mapped_column(String(100))  # chữ AI nghe được: "Nam", "anh", "Duy"
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Kết quả ghép tên: exact | no_accent | fuzzy | ambiguous | self | group | none
    assignee_match: Mapped[str] = mapped_column(String(20), default="none")
    assignee_score: Mapped[int] = mapped_column(Integer, default=0)
    # Khi ambiguous (2 thành viên trùng tên): id các tài khoản có thể đúng, để gợi ý lúc duyệt
    assignee_candidates: Mapped[list[int]] = mapped_column(JSONB, default=list)
    # F20: tên dạng chữ dùng khi đẩy lên bảng nếu chưa chọn được tài khoản ("Duy" chưa đăng ký)
    assignee_name: Mapped[str | None] = mapped_column(String(100))

    # --- Hạn chót (F16) ---
    due_text: Mapped[str | None] = mapped_column(String(200))  # nguyên văn: "thứ Sáu tuần này"
    due_date: Mapped[date | None] = mapped_column(Date)  # ngày đã tính theo ngày họp
    due_approximate: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    priority: Mapped[str] = mapped_column(String(10), default="medium")

    # --- Bằng chứng: câu gốc trong bản ghi ---
    evidence_quote: Mapped[str] = mapped_column(Text, default="")
    evidence_found: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    evidence_segment: Mapped[int | None] = mapped_column(Integer)
    evidence_start: Mapped[float | None] = mapped_column(Float)  # giây, để nghe lại đúng câu

    status: Mapped[str] = mapped_column(String(10), default=ExtractedTaskStatus.PENDING)
    # --- Duyệt (Giai đoạn 5) ---
    selected: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")  # có tick "đưa lên bảng" không
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))  # thẻ đã tạo
    # Tóm tắt lại sau khi đã đẩy: việc này giống một thẻ đã có trên bảng → bỏ tick sẵn
    duplicate_of_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meeting: Mapped[Meeting] = relationship(back_populates="extracted_tasks")
    assignee: Mapped[User | None] = relationship(lazy="joined")
    task: Mapped["Task | None"] = relationship(foreign_keys=[task_id])  # noqa: F821 — app.models.board
