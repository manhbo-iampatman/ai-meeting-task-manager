"""F09–F18: tạo cuộc họp, tải ghi âm / văn bản, theo dõi xử lý, xem & sửa bản ghi, tóm tắt bằng AI,
duyệt đầu việc và đẩy lên bảng."""

from datetime import date

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, ensure_member_user, get_board_for_member, get_membership
from app.api.routes.boards import board_changed
from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.core.realtime import publish_event, workspace_room
from app.models import ExtractedTask, ExtractedTaskStatus, Meeting, MeetingStatus, User, WorkspaceMember
from app.schemas.meeting import (
    ExtractedTaskOut,
    ExtractedTaskUpdate,
    MeetingDetail,
    MeetingOut,
    MeetingUpdate,
    PushIn,
    SummaryOut,
    TranscriptOut,
    TranscriptUpdate,
)
from app.services import meeting_service as svc
from app.services import review_service

router = APIRouter(tags=["meetings"])


def _get_meeting(db: DB, meeting_id: int, user: User) -> Meeting:
    m = db.get(Meeting, meeting_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy cuộc họp")
    get_membership(db, m.workspace_id, user)
    return m


def _out(m: Meeting) -> MeetingOut:
    out = MeetingOut.model_validate(m)
    out.duration_sec = m.transcript.duration_sec if m.transcript else None
    return out


def _summary_out(m: Meeting) -> SummaryOut | None:
    sm = m.summary
    if sm is None:
        return None
    data = sm.summary or {}
    return SummaryOut(
        topic=data.get("topic") or "",
        key_points=data.get("key_points") or [],
        decisions=data.get("decisions") or [],
        open_issues=data.get("open_issues") or [],
        llm_model=sm.llm_model,
        fallback_from=sm.fallback_from,
        chunk_count=sm.chunk_count,
        processing_sec=sm.processing_sec,
        created_at=sm.created_at,
        # Bản ghi bị sửa sau lần tóm tắt gần nhất → biên bản có thể đã cũ
        stale=bool(m.transcript and m.transcript.updated_at > sm.created_at),
    )


def _draft_out(t: ExtractedTask) -> ExtractedTaskOut:
    out = ExtractedTaskOut.model_validate(t)
    out.task_board_id = t.task.board_id if t.task else None
    return out


def _detail(m: Meeting, db: DB, user: User) -> MeetingDetail:
    return MeetingDetail(
        **_out(m).model_dump(),
        has_audio=bool(m.audio_path),
        transcript=TranscriptOut.model_validate(m.transcript) if m.transcript else None,
        summary=_summary_out(m),
        extracted_tasks=[_draft_out(t) for t in m.extracted_tasks],
        can_review=review_service.can_review(db, m, user),
    )


@router.get("/workspaces/{workspace_id}/meetings", response_model=list[MeetingOut])
def list_meetings(workspace_id: int, user: CurrentUser, db: DB):
    get_membership(db, workspace_id, user)
    meetings = db.scalars(
        select(Meeting)
        .where(Meeting.workspace_id == workspace_id)
        .order_by(Meeting.meeting_date.desc(), Meeting.id.desc())
    ).all()
    return [_out(m) for m in meetings]


@router.post("/workspaces/{workspace_id}/meetings", response_model=MeetingDetail, status_code=status.HTTP_201_CREATED)
def create_meeting(
    workspace_id: int,
    user: CurrentUser,
    db: DB,
    title: str = Form(min_length=1, max_length=200),
    meeting_date: date = Form(),
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None, max_length=500_000),
    recorded: bool = Form(default=False),  # true = ghi âm trực tiếp trên trình duyệt
):
    """Tạo cuộc họp từ 1 trong 3 nguồn: file ghi âm, file .txt, hoặc văn bản dán vào.

    - Ghi âm → lưu file, đưa vào hàng đợi, trả về NGAY (status = queued).
    - Văn bản → tạo bản ghi luôn (status = transcribed).
    """
    get_membership(db, workspace_id, user)
    has_file = file is not None and bool(file.filename)
    has_text = bool(text and text.strip())
    if has_file == has_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hãy chọn 1 file ghi âm HOẶC dán văn bản")

    ext = svc.file_ext(file.filename) if has_file else ""
    if has_file and ext not in svc.AUDIO_EXTS | svc.TEXT_EXTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Định dạng không hỗ trợ. Dùng: mp3, m4a, wav, webm, ogg, aac, flac, mp4 hoặc .txt",
        )

    is_audio = has_file and ext in svc.AUDIO_EXTS
    m = Meeting(
        workspace_id=workspace_id,
        title=title.strip(),
        meeting_date=meeting_date,
        source_type=("recording" if recorded else "audio") if is_audio else "text",
        status=MeetingStatus.UPLOADED,
        progress=0,
        created_by=user.id,
    )
    db.add(m)
    db.flush()  # để có m.id đặt tên file

    if is_audio:
        svc.save_audio(file, m)
        db.commit()
        svc.enqueue_transcription(m)
    else:
        if has_file:
            raw = file.file.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File văn bản quá lớn (tối đa 5MB)")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "File .txt phải dùng mã hóa UTF-8") from None
        svc.set_transcript_from_text(db, m, text or "")
    db.commit()
    db.refresh(m)
    svc.notify_meeting(m)
    return _detail(m, db, user)


@router.get("/meetings/{meeting_id}", response_model=MeetingDetail)
def get_meeting(meeting_id: int, user: CurrentUser, db: DB):
    return _detail(_get_meeting(db, meeting_id, user), db, user)


@router.patch("/meetings/{meeting_id}", response_model=MeetingDetail)
def update_meeting(meeting_id: int, data: MeetingUpdate, user: CurrentUser, db: DB):
    m = _get_meeting(db, meeting_id, user)
    if data.title is not None:
        m.title = data.title.strip()
    if data.meeting_date is not None:
        m.meeting_date = data.meeting_date
    db.commit()
    db.refresh(m)
    svc.notify_meeting(m)
    return _detail(m, db, user)


@router.delete("/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: int, user: CurrentUser, db: DB):
    m = _get_meeting(db, meeting_id, user)
    svc.delete_audio(m)
    ws_id, mid = m.workspace_id, m.id
    db.delete(m)
    db.commit()
    publish_event(workspace_room(ws_id), {"type": "meeting_deleted", "meeting_id": mid})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/meetings/{meeting_id}/retry", response_model=MeetingDetail)
def retry_meeting(meeting_id: int, user: CurrentUser, db: DB):
    """Chạy lại chuyển giọng nói (khi lỗi, hoặc muốn chạy lại sau khi đổi mô hình)."""
    m = _get_meeting(db, meeting_id, user)
    if m.source_type == "text" or not m.audio_path:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cuộc họp này không có file ghi âm")
    if m.status in MeetingStatus.PROCESSING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cuộc họp đang được xử lý")
    svc.clear_ai_results(db, m)  # bản ghi sắp được thay mới → biên bản cũ không còn đúng
    svc.enqueue_transcription(m)
    db.commit()
    db.refresh(m)
    svc.notify_meeting(m)
    return _detail(m, db, user)


@router.put("/meetings/{meeting_id}/transcript", response_model=MeetingDetail)
def update_transcript(meeting_id: int, data: TranscriptUpdate, user: CurrentUser, db: DB):
    """F12: người dùng sửa lỗi nhận dạng (tên riêng, thuật ngữ...) trước khi đưa cho AI tóm tắt."""
    m = _get_meeting(db, meeting_id, user)
    if m.transcript is None or m.status in MeetingStatus.PROCESSING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bản ghi chưa sẵn sàng để sửa")
    segments = [s.model_dump() for s in data.segments if s.text.strip()]
    if not segments:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bản ghi không được để trống")
    for s in segments:
        s["text"] = s["text"].strip()
    m.transcript.segments = segments
    m.transcript.full_text = ("\n" if m.source_type == "text" else " ").join(s["text"] for s in segments)
    m.transcript.edited = True
    db.commit()
    db.refresh(m)
    svc.notify_meeting(m)
    return _detail(m, db, user)


@router.post("/meetings/{meeting_id}/summarize", response_model=MeetingDetail)
def summarize_meeting(meeting_id: int, user: CurrentUser, db: DB):
    """F13–F16: nhờ AI tóm tắt cuộc họp và tách đầu việc (Ai làm – Làm gì – Hạn chót).

    Chỉ đưa việc vào hàng đợi rồi trả về NGAY (status = summarizing); worker gọi LLM ở
    tiến trình riêng. Gọi lại lần nữa = tóm tắt lại, kết quả cũ bị thay thế.
    """
    m = _get_meeting(db, meeting_id, user)
    if m.status in MeetingStatus.PROCESSING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cuộc họp đang được xử lý")
    if m.transcript is None or not m.transcript.segments:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cuộc họp chưa có bản ghi để tóm tắt")
    svc.enqueue_summarization(m)
    db.commit()
    db.refresh(m)
    svc.notify_meeting(m)
    return _detail(m, db, user)


# ---------- Giai đoạn 5: duyệt đầu việc nháp và đẩy lên bảng (F17) ----------


@router.patch("/extracted-tasks/{draft_id}", response_model=MeetingDetail)
def update_draft(draft_id: int, data: ExtractedTaskUpdate, user: CurrentUser, db: DB):
    """Người duyệt sửa một đầu việc nháp (tiêu đề, người làm, hạn, ưu tiên, tick)."""
    d = db.get(ExtractedTask, draft_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đầu việc")
    m = _get_meeting(db, d.meeting_id, user)
    review_service.require_reviewer(db, m, user)
    if m.status in MeetingStatus.PROCESSING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cuộc họp đang được xử lý")
    if d.status == ExtractedTaskStatus.ACCEPTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Việc này đã lên bảng — hãy sửa trực tiếp trên bảng")

    changes = data.model_dump(exclude_unset=True)
    if "title" in changes:
        if not changes["title"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tiêu đề không được để trống")
        d.title = changes["title"]
    if "assignee_id" in changes or "assignee_name" in changes:
        uid, name = changes.get("assignee_id"), changes.get("assignee_name") or None
        if uid is not None:
            ensure_member_user(db, m.workspace_id, uid)
            name = None  # đã chọn tài khoản thì bỏ tên chữ
        d.assignee_id, d.assignee_name = uid, name
        d.assignee_match = "manual"  # người duyệt tự chọn
    if "due_date" in changes:
        d.due_date = changes["due_date"]
        d.due_approximate = False  # người duyệt đã chọn ngày → không còn là ước lượng
    if changes.get("priority"):
        d.priority = changes["priority"]
    if "selected" in changes and changes["selected"] is not None:
        d.selected = changes["selected"]
        if d.selected and d.status == ExtractedTaskStatus.REJECTED:
            d.status = ExtractedTaskStatus.PENDING  # tick lại việc đã bỏ
    db.commit()
    db.refresh(d)  # nạp lại quan hệ `assignee` sau khi đổi người làm
    db.refresh(m)
    return _detail(m, db, user)


@router.post("/meetings/{meeting_id}/push", response_model=MeetingDetail)
def push_to_board(meeting_id: int, data: PushIn, user: CurrentUser, db: DB, background: BackgroundTasks):
    """F17: "Đẩy lên bảng" — các việc đang tick thành thẻ thật, trong MỘT transaction."""
    m = _get_meeting(db, meeting_id, user)
    review_service.require_reviewer(db, m, user)
    board = get_board_for_member(db, data.board_id, user)
    created = review_service.push_to_board(db, m, board, user)
    db.commit()
    db.refresh(m)
    board_changed(background, board.id, user.id)
    svc.notify_meeting(m)
    if any(t.assignee_name for t in created):  # có tên mới chờ người nhận (F21)
        publish_event(workspace_room(m.workspace_id), {"type": "names_updated"})
    return _detail(m, db, user)


@router.get("/meetings/{meeting_id}/audio")
def get_audio(meeting_id: int, token: str):
    """Phát lại file ghi âm.

    Thẻ <audio> của trình duyệt không gửi được header Authorization → nhận token qua
    query string. FileResponse hỗ trợ "Range request" nên tua được tới giữa file.
    """
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Phiên đăng nhập không hợp lệ")
    with SessionLocal() as db:
        m = db.get(Meeting, meeting_id)
        if m is None or db.get(WorkspaceMember, (m.workspace_id, user_id)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy cuộc họp")
        path = svc.audio_abspath(m)
        if path is None or not path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Không có file ghi âm")
        return FileResponse(
            path,
            media_type=m.audio_mime or "application/octet-stream",
            filename=m.audio_filename,
            content_disposition_type="inline",
        )
