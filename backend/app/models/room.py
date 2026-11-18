from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.user import User


class RoomStatus:
    OPEN = "open"  # đang họp (hoặc vừa mở, chờ người vào)
    ENDED = "ended"  # đã kết thúc — link phòng hết dùng được


class MeetingRoom(TimestampMixin, Base):
    """Một BUỔI họp trực tuyến "Online Meeting" (Giai đoạn 6).

    Phòng chỉ sống trong buổi họp đó: mỗi buổi một phòng + một link mới. Nhóm (workspace)
    thì lâu dài. Buổi họp có ghi âm → khi kết thúc sinh ra một `Meeting` (nguồn "online")
    đi tiếp pipeline cũ: nhận dạng → tóm tắt → duyệt → đẩy lên bảng.

        open ──chủ phòng bấm kết thúc / không còn ai──► ended ──đủ ghi âm hoặc hết 2 phút chờ──► finalized
    """

    __tablename__ = "meeting_rooms"
    __table_args__ = (
        # Mỗi nhóm chỉ có MỘT phòng đang mở. Ràng buộc đặt ở CSDL (chỉ mục duy nhất có điều
        # kiện) nên hai người bấm "Online Meeting" cùng lúc cũng không tạo ra hai phòng.
        Index("uq_open_room_per_workspace", "workspace_id", unique=True, postgresql_where=text("status = 'open'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    # Mã ngẫu nhiên trong link /room/<mã>; cũng là tên phòng bên LiveKit
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    host_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # chủ phòng
    status: Mapped[str] = mapped_column(String(10), default=RoomStatus.OPEN, index=True)

    # Ghi âm MỘT MẠCH: bắt đầu một lần, dừng rồi thì buổi đó không ghi lại nữa
    recording_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recording_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lần đầu thấy phòng không còn ai (để tự đóng sau 30 giây)
    empty_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lần đầu có người lấy vé vào phòng. Giao diện chỉ tạo phòng khi người mở bấm "Vào phòng" nên
    # hai việc này xảy ra liền nhau; còn rỗng nghĩa là tạo xong nhưng chưa vào được.
    first_joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lần đầu thấy chủ phòng không có mặt trong khi phòng còn người khác (vắng quá 1 phút thì
    # nhượng quyền chủ phòng cho người vào sớm nhất còn lại)
    host_absent_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Cuộc họp sinh ra từ buổi này (None = không ghi âm → không có cuộc họp)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"))
    # Đã đưa cuộc họp vào hàng đợi nhận dạng chưa (ghi âm về sau mốc này là "đến muộn")
    finalized: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    host: Mapped[User | None] = relationship(lazy="joined")
    tracks: Mapped[list["MeetingTrack"]] = relationship(
        back_populates="room", order_by="MeetingTrack.id", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def recording(self) -> str:
        """idle (chưa ghi) | on (đang ghi) | stopped (đã dừng — không ghi lại được)."""
        if self.recording_started_at is None:
            return "idle"
        return "stopped" if self.recording_stopped_at is not None else "on"


class MeetingTrack(Base):
    """Ghi âm của MỘT người trong một buổi Online Meeting.

    Trình duyệt mỗi người tự ghi mic của mình và gửi lên từng khúc. Vì mỗi file chỉ có một
    giọng, hệ thống biết chắc "ai nói câu nào" mà không cần AI tách người nói (diarization).
    Một người rời phòng rồi vào lại sẽ có thêm một track mới.
    """

    __tablename__ = "meeting_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("meeting_rooms.id", ondelete="CASCADE"), index=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    speaker_name: Mapped[str] = mapped_column(String(100))  # họ tên lúc ghi — nhãn người nói trong bản ghi

    # Thời điểm (theo đồng hồ MÁY CHỦ) trình duyệt bắt đầu ghi. Hiệu với `recording_started_at`
    # của phòng = độ lệch để xếp lời của mọi người lên chung một trục thời gian.
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    audio_path: Mapped[str | None] = mapped_column(String(500))
    audio_mime: Mapped[str | None] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    next_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # khúc tiếp theo đang chờ
    finished: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # trình duyệt báo đã gửi hết

    # --- Kết quả nhận dạng của riêng track này (mốc thời gian đã cộng độ lệch) ---
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    transcribed_size: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")  # đã nhận dạng tới byte nào
    duration_sec: Mapped[float | None] = mapped_column(Float)
    # `segments` đã nằm trong bản ghi của cuộc họp chưa
    merged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    room: Mapped[MeetingRoom] = relationship(back_populates="tracks")

    @property
    def has_new_audio(self) -> bool:
        """Có phần ghi âm về SAU lần nhận dạng gần nhất (đến muộn) không."""
        return self.size > self.transcribed_size
