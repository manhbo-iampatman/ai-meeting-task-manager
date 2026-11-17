"""Các job chạy trong worker (tiến trình riêng, có GPU).

Worker lấy job từ hàng đợi Redis `meetings` và gọi hàm tương ứng ở đây.
"""

import logging
import time

from sqlalchemy import func, select

from app.ai.extraction import extract_meeting
from app.ai.llm import LLMError, get_llm_provider
from app.ai.postprocess.name_matching import MemberInfo
from app.ai.stt import get_stt_provider
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import ExtractedTask, Meeting, MeetingStatus, MeetingSummary, Transcript, WorkspaceMember
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


def workspace_members(db, workspace_id: int) -> list[MemberInfo]:
    """Danh sách thành viên + biệt danh — đưa vào prompt cho LLM và dùng để ghép tên."""
    members = db.scalars(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id).order_by(WorkspaceMember.joined_at)
    ).all()
    return [MemberInfo(user_id=m.user_id, full_name=m.user.full_name, nicknames=list(m.nicknames or [])) for m in members]


def summarize_meeting_job(meeting_id: int) -> dict:
    """Giai đoạn 4: gọi LLM tóm tắt bản ghi + trích xuất đầu việc, rồi lưu thành BẢN NHÁP chờ duyệt.

    Lỗi (hết hạn mức Gemini, mất mạng...) KHÔNG làm mất bản ghi: cuộc họp quay về trạng thái
    trước đó kèm thông báo lỗi, người dùng bấm tóm tắt lại là được.
    """
    with SessionLocal() as db:
        m = db.get(Meeting, meeting_id)
        if m is None:  # cuộc họp đã bị xóa trong lúc chờ
            return {"skipped": True}
        tr = m.transcript
        segments = list(tr.segments) if tr else []
        meeting_date, workspace_id = m.meeting_date, m.workspace_id

        m.status, m.progress, m.error, m.status_note = MeetingStatus.SUMMARIZING, 5, None, None
        db.commit()
        notify_meeting(m)

        def on_progress(p: float) -> None:
            m.progress = min(95, 5 + int(p * 90))
            db.commit()
            notify_meeting(m)

        def on_notice(message: str) -> None:
            """Mô hình chính quá tải → hiện thông báo "đã chuyển sang mô hình dự phòng…" ngay lúc chuyển."""
            m.status_note = message
            db.commit()
            notify_meeting(m)

        def fail(message: str) -> dict:
            db.rollback()
            db.expire_all()
            mm = db.get(Meeting, meeting_id)
            if mm is None:
                return {"skipped": True}
            # Còn biên bản cũ thì vẫn ở bước duyệt; chưa có thì quay về "đã có bản ghi"
            mm.status = MeetingStatus.REVIEW if mm.summary else MeetingStatus.TRANSCRIBED
            mm.progress = 100
            mm.error = message
            mm.status_note = None
            db.commit()
            notify_meeting(mm)
            return {"error": message}

        try:
            llm = get_llm_provider()
            result = extract_meeting(
                llm,
                segments,
                meeting_date,
                workspace_members(db, workspace_id),
                on_progress=on_progress,
                chunk_chars=get_settings().LLM_CHUNK_CHARS or None,
                on_notice=on_notice,
            )
        except LLMError as e:  # lỗi đã có thông báo tiếng Việt rõ ràng
            log.warning("Cuộc họp %s: tóm tắt thất bại: %s", meeting_id, e)
            return fail(f"Tóm tắt thất bại: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("Lỗi tóm tắt cuộc họp %s", meeting_id)
            return fail(f"Tóm tắt thất bại: {type(e).__name__}: {str(e)[:300]}")

        db.expire_all()
        m = db.get(Meeting, meeting_id)
        if m is None:  # bị xóa trong lúc LLM đang chạy
            return {"skipped": True}

        sm = m.summary or MeetingSummary(meeting_id=m.id)
        sm.summary = result.summary
        sm.llm_model = result.llm_model
        sm.fallback_from = result.fallback_from
        sm.chunk_count = result.chunk_count
        sm.processing_sec = result.processing_sec
        sm.input_tokens = result.input_tokens
        sm.output_tokens = result.output_tokens
        sm.created_at = func.now()  # tóm tắt lại → tính là biên bản mới
        db.add(sm)

        # Thay toàn bộ đầu việc nháp cũ bằng kết quả mới
        db.query(ExtractedTask).filter(ExtractedTask.meeting_id == m.id).delete()
        for pos, it in enumerate(result.items):
            db.add(
                ExtractedTask(
                    meeting_id=m.id,
                    position=pos,
                    title=it.title,
                    raw_assignee=it.raw_assignee,
                    assignee_id=it.assignee_id,
                    assignee_match=it.assignee_match,
                    assignee_score=it.assignee_score,
                    assignee_candidates=it.assignee_candidates,
                    due_text=it.due_text,
                    due_date=it.due_date,
                    due_approximate=it.due_approximate,
                    priority=it.priority,
                    evidence_quote=it.evidence_quote,
                    evidence_found=it.evidence_found,
                    evidence_segment=it.evidence_segment,
                    evidence_start=it.evidence_start,
                )
            )
        m.status, m.progress, m.error, m.status_note = MeetingStatus.REVIEW, 100, None, None
        db.commit()
        notify_meeting(m)
        log.info(
            "Cuộc họp %s: tóm tắt xong bằng %s%s trong %.1fs — %d đầu việc, %d đoạn, %d + %d token",
            meeting_id, result.llm_model,
            f" (dự phòng thay cho {result.fallback_from})" if result.fallback_from else "",
            result.processing_sec, len(result.items),
            result.chunk_count, result.input_tokens, result.output_tokens,
        )
        return {"tasks": len(result.items), "chunks": result.chunk_count, "processing_sec": result.processing_sec}
