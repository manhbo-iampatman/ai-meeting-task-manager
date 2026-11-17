"""Các job chạy trong worker (tiến trình riêng, có GPU).

Worker lấy job từ hàng đợi Redis `meetings` và gọi hàm tương ứng ở đây.
"""

import logging
import time

from sqlalchemy import select

from app.ai.stt import get_stt_provider
from app.core.database import SessionLocal
from app.models import Meeting, MeetingStatus, Transcript, WorkspaceMember
from app.services.meeting_service import audio_abspath, fix_webm_duration, notify_meeting

log = logging.getLogger(__name__)


def build_initial_prompt(db, workspace_id: int) -> str | None:
    """Tạo câu gợi ý cho Whisper chứa tên + biệt danh thành viên nhóm.

    Ví dụ: "Cuộc họp nhóm. Thành viên: Nguyễn Văn Nam (Nam, anh Nam), Trần Thị Lan (Lan)."
    Whisper coi đây là "đoạn văn phía trước" nên có xu hướng viết đúng các tên này.
    """
    members = db.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)).all()
    if not members:
        return None
    parts = []
    for m in members:
        nick = f" ({', '.join(m.nicknames)})" if m.nicknames else ""
        parts.append(f"{m.user.full_name}{nick}")
    return ("Cuộc họp nhóm. Thành viên: " + ", ".join(parts) + ".")[:800]


def process_meeting_job(meeting_id: int) -> dict:
    """Chuyển file ghi âm của cuộc họp thành văn bản, cập nhật tiến độ theo thời gian thực."""
    with SessionLocal() as db:
        m = db.get(Meeting, meeting_id)
        if m is None:  # cuộc họp đã bị xóa trong lúc chờ
            return {"skipped": True}
        path = audio_abspath(m)
        if path is None or not path.exists():
            m.status, m.error = MeetingStatus.FAILED, "Không tìm thấy file ghi âm trên máy chủ"
            db.commit()
            notify_meeting(m)
            return {"error": m.error}

        m.status, m.progress, m.error = MeetingStatus.TRANSCRIBING, 0, None
        db.commit()
        notify_meeting(m)

        # File ghi trực tiếp trên trình duyệt (.webm) thiếu thời lượng → sửa để tua được
        if fix_webm_duration(path):
            m.audio_size = path.stat().st_size
            db.commit()

        # Báo tiến độ: tối đa ~1 lần/giây và chỉ khi tăng ≥ 1% → không "spam" CSDL và Redis
        last = {"pct": 0, "t": 0.0}

        def on_progress(p: float) -> None:
            pct = min(99, int(p * 100))
            now = time.monotonic()
            if pct > last["pct"] and now - last["t"] >= 1.0:
                last.update(pct=pct, t=now)
                m.progress = pct
                db.commit()
                notify_meeting(m)

        try:
            stt = get_stt_provider()  # lần đầu: nạp mô hình vào GPU (~5–10 giây), các lần sau dùng lại
            result = stt.transcribe(
                str(path),
                language="vi",
                on_progress=on_progress,
                initial_prompt=build_initial_prompt(db, m.workspace_id),
            )
        except Exception as e:  # noqa: BLE001
            log.exception("Lỗi chuyển giọng nói cuộc họp %s", meeting_id)
            db.rollback()
            m = db.get(Meeting, meeting_id)
            if m is None:
                return {"skipped": True}
            m.status = MeetingStatus.FAILED
            m.error = f"Lỗi xử lý ghi âm: {type(e).__name__}: {str(e)[:300]}"
            db.commit()
            notify_meeting(m)
            return {"error": m.error}

        if getattr(stt, "prompt_echo", False):
            log.info("Cuộc họp %s: Whisper chép lại gợi ý tên → đã chạy lại không dùng gợi ý", meeting_id)
        dropped = getattr(stt, "dropped", None)
        if dropped:
            log.info("Cuộc họp %s: đã lọc %d câu nghi ảo giác: %s", meeting_id, len(dropped), dropped)

        db.refresh(m)  # có thể đã bị xóa / sửa trong lúc chạy

        # Không nhận ra câu nói nào (file nhạc, im lặng, quá ồn...) → báo lỗi rõ ràng thay vì
        # "Đã có bản ghi" mà trống trơn
        if not result.segments:
            m.status = MeetingStatus.FAILED
            m.error = (
                "Không nhận ra lời nói trong file ghi âm. File có thể là nhạc, im lặng, hoặc quá ồn. "
                "Hệ thống chỉ xử lý ghi âm giọng nói (cuộc họp, cuộc gọi...)."
            )
            db.commit()
            notify_meeting(m)
            return {"error": m.error, "dropped": dropped or []}

        tr = m.transcript or Transcript(meeting_id=m.id)
        tr.segments = [s.__dict__ for s in result.segments]
        tr.full_text = result.text
        tr.language = result.language
        tr.stt_model = result.model
        tr.duration_sec = result.duration_sec
        tr.processing_sec = result.processing_sec
        tr.edited = False
        db.add(tr)
        m.status, m.progress = MeetingStatus.TRANSCRIBED, 100
        db.commit()
        notify_meeting(m)
        log.info(
            "Cuộc họp %s: %.0fs audio, xử lý %.1fs (%s)",
            meeting_id,
            result.duration_sec,
            result.processing_sec,
            result.model,
        )
        return {"duration_sec": result.duration_sec, "processing_sec": result.processing_sec, "segments": len(result.segments)}
