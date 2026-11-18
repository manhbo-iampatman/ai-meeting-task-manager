"""Nghiệp vụ cuộc họp: lưu file ghi âm, đưa vào hàng đợi, báo tiến độ."""

import logging
import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.realtime import publish_event, workspace_room
from app.models import ExtractedTask, ExtractedTaskStatus, Meeting, MeetingStatus, MeetingSummary, Transcript

log = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MAX_UPLOAD_BYTES = 300 * 1024 * 1024  # 300MB ≈ 5 giờ ghi âm mp3
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".webm", ".ogg", ".oga", ".opus", ".aac", ".flac", ".mp4", ".mpeg", ".amr", ".wma"}
TEXT_EXTS = {".txt"}
CHUNK = 1024 * 1024


def upload_root() -> Path:
    p = Path(get_settings().UPLOAD_DIR)
    if not p.is_absolute():
        p = BACKEND_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def file_ext(filename: str | None) -> str:
    return Path(filename or "").suffix.lower()


def save_audio(file: UploadFile, meeting: Meeting) -> None:
    """Ghi file xuống đĩa theo từng khối 1MB (không đọc cả file vào RAM)."""
    ext = file_ext(file.filename)
    folder = upload_root() / "meetings"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{meeting.id}{ext}"
    size = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(CHUNK):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File quá lớn (tối đa 300MB)")
            out.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File rỗng")
    meeting.audio_path = str(dest.relative_to(upload_root()))
    meeting.audio_filename = (file.filename or dest.name)[:255]
    meeting.audio_size = size
    meeting.audio_mime = file.content_type


def audio_abspath(meeting: Meeting) -> Path | None:
    if not meeting.audio_path:
        return None
    return upload_root() / meeting.audio_path


def delete_audio(meeting: Meeting) -> None:
    # Online Meeting: xóa luôn ghi âm riêng của từng người
    for room_id in {t.room_id for t in meeting.tracks}:
        shutil.rmtree(upload_root() / "rooms" / str(room_id), ignore_errors=True)
    p = audio_abspath(meeting)
    if p:
        try:
            p.unlink(missing_ok=True)
        except OSError as e:  # file đang bị worker mở (Windows khóa file) → bỏ qua
            log.warning("Không xóa được %s: %s", p, e)


def fix_webm_duration(path: Path) -> bool:
    """Ghi âm từ trình duyệt (MediaRecorder) ra file .webm KHÔNG có thông tin thời lượng
    (vì trình duyệt ghi theo luồng, không biết trước khi nào dừng) → thẻ <audio> hiện
    độ dài "vô cực" và không tua được.

    Cách sửa: "remux" — đọc từng gói dữ liệu rồi ghi sang file mới (KHÔNG mã hóa lại,
    chất lượng giữ nguyên, rất nhanh). Bộ ghi webm sẽ tự điền thời lượng + bảng mục lục
    (cues) để tua. Lỗi thì giữ nguyên file cũ (vẫn chuyển giọng nói được bình thường).
    """
    if path.suffix.lower() != ".webm":
        return False
    import av

    tmp = path.with_suffix(".remux.webm")
    try:
        with av.open(str(path)) as src, av.open(str(tmp), "w", format="webm") as dst:
            in_stream = next(s for s in src.streams if s.type == "audio")
            out_stream = dst.add_stream_from_template(in_stream)
            for packet in src.demux(in_stream):
                if packet.dts is None:  # gói rỗng cuối luồng
                    continue
                packet.stream = out_stream
                dst.mux(packet)
        tmp.replace(path)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Không remux được %s: %s", path, e)
        tmp.unlink(missing_ok=True)
        return False


def text_to_segments(text: str) -> list[dict]:
    """Văn bản dán vào → mỗi dòng không rỗng là 1 đoạn (không có mốc thời gian)."""
    return [{"start": None, "end": None, "text": line.strip()} for line in text.splitlines() if line.strip()]


def set_transcript_from_text(db: Session, meeting: Meeting, text: str) -> None:
    segments = text_to_segments(text)
    if not segments:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nội dung văn bản trống")
    tr = meeting.transcript or Transcript(meeting_id=meeting.id)
    tr.segments = segments
    tr.full_text = "\n".join(s["text"] for s in segments)
    tr.language = "vi"
    tr.stt_model = "manual-text"
    db.add(tr)
    meeting.status = MeetingStatus.TRANSCRIBED
    meeting.progress = 100


def notify_meeting(meeting: Meeting) -> None:
    """Báo cho mọi người đang mở trang nhóm / trang cuộc họp."""
    publish_event(
        workspace_room(meeting.workspace_id),
        {
            "type": "meeting_updated",
            "meeting_id": meeting.id,
            "status": meeting.status,
            "progress": meeting.progress,
            "status_note": meeting.status_note,
        },
    )


def enqueue_transcription(meeting: Meeting) -> None:
    """Đưa cuộc họp vào hàng đợi Redis để worker chuyển giọng nói thành văn bản.

    API trả kết quả NGAY, không chờ. Worker xử lý ở tiến trình riêng.
    """
    from app.core.queue import meeting_queue

    try:
        job = meeting_queue.enqueue(
            # Online Meeting: nhận dạng từng người một rồi ghép lại (có tên người nói)
            "app.workers.online_jobs.process_online_meeting_job" if meeting.source_type == "online" else "app.workers.jobs.process_meeting_job",
            meeting.id,
            job_timeout=2 * 60 * 60,  # tối đa 2 giờ / file
            result_ttl=24 * 60 * 60,
            failure_ttl=7 * 24 * 60 * 60,
        )
        meeting.job_id = job.id
        meeting.status = MeetingStatus.QUEUED
        meeting.progress = 0
        meeting.error = None
        meeting.status_note = None
    except Exception as e:  # noqa: BLE001 — Redis chưa chạy
        log.error("Không đưa được vào hàng đợi: %s", e)
        meeting.status = MeetingStatus.FAILED
        meeting.error = "Không kết nối được hàng đợi (Redis). Hãy bật Docker rồi bấm Thử lại."


def enqueue_late_track(track_id: int, force: bool = False) -> None:
    """Online Meeting: ghi âm của một người về SAU khi cuộc họp đã được nhận dạng → nhận dạng bổ sung.

    `force=True`: người duyệt đã bấm "Bổ sung" → đưa vào bản ghi dù bản ghi đã sửa tay / đã tóm tắt.
    """
    from app.core.queue import meeting_queue

    try:
        meeting_queue.enqueue(
            "app.workers.online_jobs.process_late_track_job",
            track_id,
            force,
            job_timeout=2 * 60 * 60,
            result_ttl=24 * 60 * 60,
            failure_ttl=7 * 24 * 60 * 60,
        )
    except Exception as e:  # noqa: BLE001 — Redis chưa chạy
        log.error("Không đưa được ghi âm đến muộn vào hàng đợi: %s", e)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Không kết nối được hàng đợi (Redis). Hãy bật Docker rồi thử lại."
        ) from e


def enqueue_summarization(meeting: Meeting) -> None:
    """Đưa cuộc họp vào hàng đợi để worker gọi LLM tóm tắt + trích xuất đầu việc (Giai đoạn 4).

    Dùng chung hàng đợi với bước chuyển giọng nói → worker vẫn xử lý lần lượt từng việc.
    """
    from app.core.queue import meeting_queue

    try:
        job = meeting_queue.enqueue(
            "app.workers.jobs.summarize_meeting_job",
            meeting.id,
            job_timeout=30 * 60,
            result_ttl=24 * 60 * 60,
            failure_ttl=7 * 24 * 60 * 60,
        )
    except Exception as e:  # noqa: BLE001 — Redis chưa chạy
        log.error("Không đưa được vào hàng đợi: %s", e)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Không kết nối được hàng đợi (Redis). Hãy bật Docker rồi thử lại."
        ) from e
    meeting.job_id = job.id
    meeting.status = MeetingStatus.SUMMARIZING
    meeting.progress = 0
    meeting.error = None
    meeting.status_note = None


def clear_ai_results(db: Session, meeting: Meeting) -> None:
    """Xóa biên bản + đầu việc nháp (khi nhận dạng lại giọng nói → bản ghi cũ không còn đúng).

    Đầu việc ĐÃ ĐẨY lên bảng được giữ lại: thẻ trên bảng vẫn còn, cần truy vết được nguồn gốc (F18).
    """
    db.query(ExtractedTask).filter(
        ExtractedTask.meeting_id == meeting.id, ExtractedTask.status != ExtractedTaskStatus.ACCEPTED
    ).delete()
    db.query(MeetingSummary).filter(MeetingSummary.meeting_id == meeting.id).delete()
    db.expire(meeting, ["summary", "extracted_tasks"])
