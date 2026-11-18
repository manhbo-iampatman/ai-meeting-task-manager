"""Nghiệp vụ phòng họp trực tuyến "Online Meeting" (Giai đoạn 6).

    mở phòng ──► mọi người vào (cấp vé LiveKit) ──► chủ phòng "Bắt đầu ghi"
        ──► trình duyệt MỖI NGƯỜI tự ghi mic của mình, gửi dần từng khúc lên đây
        ──► kết thúc phòng ──► chờ ghi âm về đủ (tối đa 2 phút) ──► worker nhận dạng từng người
        ──► bản ghi có tên người nói ──► pipeline GĐ4–5 như mọi cuộc họp khác

Các hàm ở đây chỉ `flush`, route / tác vụ nền gọi `commit`.
"""

import logging
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import livekit as lk
from app.core.config import get_settings
from app.core.realtime import publish_event, workspace_room
from app.models import Meeting, MeetingRoom, MeetingStatus, MeetingTrack, RoomStatus, User, Workspace, WorkspaceMember
from app.services import meeting_service

log = logging.getLogger(__name__)

MAX_CHUNK_BYTES = 8 * 1024 * 1024  # một khúc ~5 giây chỉ vài chục KB; 8MB là quá thừa
WAITING_NOTE = "Đang chờ ghi âm của mọi người gửi về…"


def now_utc() -> datetime:
    return datetime.now(UTC)


# ---------- Quyền ----------


def is_member(db: Session, workspace_id: int, user_id: int) -> bool:
    return db.get(WorkspaceMember, (workspace_id, user_id)) is not None


def can_control(db: Session, room: MeetingRoom, user: User) -> bool:
    """Ai được bắt đầu / dừng ghi và kết thúc phòng: chủ phòng + trưởng nhóm."""
    if room.host_id == user.id:
        return True
    ws = db.get(Workspace, room.workspace_id)
    return ws is not None and ws.owner_id == user.id


def require_control(db: Session, room: MeetingRoom, user: User) -> None:
    if not can_control(db, room, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ chủ phòng hoặc trưởng nhóm được làm thao tác này")


# ---------- Mở phòng / vào phòng ----------


def get_open_room(db: Session, workspace_id: int) -> MeetingRoom | None:
    return db.scalar(
        select(MeetingRoom).where(MeetingRoom.workspace_id == workspace_id, MeetingRoom.status == RoomStatus.OPEN)
    )


def get_room_by_code(db: Session, code: str) -> MeetingRoom:
    room = db.scalar(select(MeetingRoom).where(MeetingRoom.code == code.strip()))
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link phòng họp không đúng")
    return room


def metadata(room: MeetingRoom) -> dict:
    """Thông tin phòng gửi cho mọi trình duyệt qua LiveKit: trạng thái ghi âm."""
    return {
        "recording": room.recording,
        "recording_started_at": room.recording_started_at.isoformat() if room.recording_started_at else None,
        "host_id": room.host_id,  # đổi chủ phòng → mọi trình duyệt trong phòng biết ngay
    }


def notify_room(room: MeetingRoom) -> None:
    """Báo cho mọi người đang mở trang nhóm: nút "Online Meeting" ↔ "Tham gia phòng"."""
    publish_event(
        workspace_room(room.workspace_id),
        {
            "type": "room_updated",
            "room_code": room.code,
            "status": room.status,
            "recording": room.recording,
            "host_id": room.host_id,
        },
    )


def open_room(db: Session, workspace_id: int, user: User, title: str | None) -> tuple[MeetingRoom, bool]:
    """Mở phòng cho nhóm. Nhóm đang có phòng mở → trả về chính phòng đó (không tạo phòng thứ hai).

    Trả về (phòng, vừa_tạo_mới).
    """
    existing = get_open_room(db, workspace_id)
    if existing:
        return existing, False

    code = secrets.token_urlsafe(9)  # 12 ký tự ngẫu nhiên, khó đoán — như mã mời nhóm
    room = MeetingRoom(
        workspace_id=workspace_id,
        code=code,
        title=(title or "").strip() or f"Online Meeting {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        host_id=user.id,
        status=RoomStatus.OPEN,
    )
    db.add(room)
    try:
        db.flush()
    except IntegrityError:
        # Hai người bấm cùng lúc: chỉ mục duy nhất "một phòng mở mỗi nhóm" chặn người đến sau
        db.rollback()
        existing = get_open_room(db, workspace_id)
        if existing:
            return existing, False
        raise
    try:
        lk.get_livekit().create_room(code, metadata(room))
    except lk.LiveKitError as e:
        db.rollback()
        log.error("Không tạo được phòng LiveKit: %s", e)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Chưa bật máy chủ phòng họp (LiveKit). Hãy mở Docker Desktop rồi chạy: docker compose up -d",
        ) from e
    return room, True


def join_room(db: Session, room: MeetingRoom, user: User) -> tuple[str, bool]:
    """Cấp vé vào phòng. Người chưa ở trong nhóm → tự thêm vào nhóm (link phòng hoạt động như
    link mời, giống Google Meet). Trả về (vé LiveKit, vừa_vào_nhóm)."""
    if room.status != RoomStatus.OPEN:
        raise HTTPException(status.HTTP_410_GONE, "Phòng họp này đã kết thúc")

    joined_workspace = False
    if not is_member(db, room.workspace_id, user.id):
        db.add(WorkspaceMember(workspace_id=room.workspace_id, user_id=user.id, role="member", nicknames=[]))
        db.flush()
        joined_workspace = True

    # Phòng đủ người thì báo lỗi dễ hiểu ngay ở đây (LiveKit cũng tự chặn ở tầng dưới)
    try:
        inside = lk.get_livekit().participant_ids(room.code)
    except lk.LiveKitError as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Không kết nối được máy chủ phòng họp (LiveKit). Hãy kiểm tra Docker.",
        ) from e
    limit = get_settings().ROOM_MAX_PARTICIPANTS
    if inside is not None and user.id not in inside and len(inside) >= limit:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Phòng đã đủ {limit} người")

    if room.first_joined_at is None:
        room.first_joined_at = now_utc()
        db.flush()
    return lk.create_join_token(room.code, user.id, user.full_name), joined_workspace


# ---------- Chủ phòng rời phòng / vắng mặt ----------


def transfer_host(db: Session, room: MeetingRoom, new_host_id: int) -> None:
    """Nhượng quyền chủ phòng. Chủ phòng mới được bắt đầu / dừng ghi, kết thúc phòng, và sau buổi
    họp là người được duyệt đầu việc (cùng với trưởng nhóm)."""
    room.host_id = new_host_id
    room.host_absent_since = None
    db.flush()
    _push_metadata(room)


def leave_room(db: Session, room: MeetingRoom, user: User) -> Meeting | None:
    """Người dùng chủ động bấm "Rời phòng".

    - Không phải chủ phòng → không có gì để làm (LiveKit tự biết người đó đã rời).
    - Chủ phòng rời, phòng còn người → NGAY LẬP TỨC nhượng quyền cho người vào sớm nhất còn lại.
    - Chủ phòng là người cuối cùng → rời là kết thúc buổi họp luôn.

    Trả về cuộc họp nếu phòng vừa kết thúc và có ghi âm.
    """
    if room.status != RoomStatus.OPEN or room.host_id != user.id:
        return None
    try:
        inside = lk.get_livekit().participant_ids(room.code) or []
    except lk.LiveKitError:
        return None  # không hỏi được LiveKit → để tác vụ nền xử lý sau (chủ phòng vắng 1 phút)
    others = [uid for uid in inside if uid != user.id]
    if others:
        transfer_host(db, room, others[0])
        return None
    return end_room(db, room)


# ---------- Ghi âm ----------


def _push_metadata(room: MeetingRoom) -> None:
    try:
        lk.get_livekit().set_metadata(room.code, metadata(room))
    except lk.LiveKitError as e:  # trình duyệt vẫn biết qua lần hỏi trạng thái định kỳ
        log.warning("Không báo được trạng thái ghi âm cho phòng %s: %s", room.code, e)


def start_recording(db: Session, room: MeetingRoom) -> None:
    if room.status != RoomStatus.OPEN:
        raise HTTPException(status.HTTP_410_GONE, "Phòng họp này đã kết thúc")
    if room.recording == "on":
        raise HTTPException(status.HTTP_409_CONFLICT, "Phòng đang được ghi âm rồi")
    if room.recording == "stopped":
        raise HTTPException(status.HTTP_409_CONFLICT, "Buổi họp này đã dừng ghi âm, không ghi lại được")
    room.recording_started_at = now_utc()
    db.flush()
    _push_metadata(room)


def stop_recording(db: Session, room: MeetingRoom) -> None:
    if room.recording != "on":
        raise HTTPException(status.HTTP_409_CONFLICT, "Phòng không ở trạng thái đang ghi âm")
    room.recording_stopped_at = now_utc()
    db.flush()
    _push_metadata(room)


# ---------- Ghi âm của từng người (track) ----------


def tracks_root(room_id: int) -> Path:
    p = meeting_service.upload_root() / "rooms" / str(room_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def track_abspath(track: MeetingTrack) -> Path | None:
    return meeting_service.upload_root() / track.audio_path if track.audio_path else None


def create_track(db: Session, room: MeetingRoom, user: User, mime: str, elapsed_ms: int) -> MeetingTrack:
    """Trình duyệt vừa bắt đầu ghi mic → mở một track. `elapsed_ms` = máy ghi đã chạy được bao lâu
    (đo bằng đồng hồ của trình duyệt) → suy ra thời điểm bắt đầu theo đồng hồ MÁY CHỦ, để mọi
    track dùng chung một đồng hồ dù máy mỗi người lệch giờ nhau."""
    if room.recording != "on" or room.status != RoomStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "Phòng không ở trạng thái đang ghi âm")
    started = now_utc() - timedelta(milliseconds=max(0, min(elapsed_ms, 60_000)))
    track = MeetingTrack(
        room_id=room.id,
        user_id=user.id,
        speaker_name=user.full_name[:100],
        started_at=max(started, room.recording_started_at),
        audio_mime=mime[:100] or "audio/webm",
    )
    db.add(track)
    db.flush()
    ext = ".m4a" if "mp4" in mime or "aac" in mime else ".ogg" if "ogg" in mime else ".webm"
    dest = tracks_root(room.id) / f"track_{track.id}{ext}"
    dest.write_bytes(b"")  # luôn bắt đầu từ file rỗng (không nối vào file cũ trùng tên)
    track.audio_path = str(dest.relative_to(meeting_service.upload_root()))
    db.flush()
    return track


def append_chunk(db: Session, track_id: int, user: User, seq: int, data: bytes) -> int:
    """Nối một khúc ghi âm vào file của track. Trả về số thứ tự khúc tiếp theo đang chờ.

    Gửi lại khúc đã nhận (mạng chập chờn, trình duyệt gửi lại) → bỏ qua, không nối hai lần
    (idempotent). Gửi nhảy cóc → từ chối, trình duyệt gửi lại từ đúng khúc đang chờ.
    """
    # Khóa dòng trong lúc nối: hai request cho cùng track không ghi chồng lên nhau
    track = db.scalar(select(MeetingTrack).where(MeetingTrack.id == track_id).with_for_update())
    if track is None or track.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy bản ghi âm")
    if seq < track.next_seq:
        return track.next_seq
    if seq > track.next_seq:
        raise HTTPException(status.HTTP_409_CONFLICT, {"expected_seq": track.next_seq})
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Khúc ghi âm rỗng")
    if len(data) > MAX_CHUNK_BYTES or track.size + len(data) > meeting_service.MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Ghi âm quá lớn")
    path = track_abspath(track)
    assert path is not None
    with path.open("ab") as f:
        f.write(data)
    track.size += len(data)
    track.next_seq += 1
    db.flush()
    return track.next_seq


def finish_track(db: Session, track_id: int, user: User) -> MeetingTrack:
    track = db.get(MeetingTrack, track_id)
    if track is None or track.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy bản ghi âm")
    track.finished = True
    db.flush()
    return track


# ---------- Kết thúc phòng ----------


def end_room(db: Session, room: MeetingRoom) -> Meeting | None:
    """Đóng phòng cho mọi người. Có ghi âm → tạo cuộc họp (nguồn "online"); không ghi âm → không tạo gì.

    Trả về cuộc họp vừa tạo (hoặc None).
    """
    if room.status == RoomStatus.ENDED:
        return db.get(Meeting, room.meeting_id) if room.meeting_id else None
    now = now_utc()
    room.status, room.ended_at = RoomStatus.ENDED, now
    if room.recording == "on":
        room.recording_stopped_at = now

    meeting: Meeting | None = None
    if room.recording_started_at is not None:
        meeting = Meeting(
            workspace_id=room.workspace_id,
            title=room.title,
            meeting_date=room.recording_started_at.astimezone().date(),
            source_type="online",
            status=MeetingStatus.UPLOADED,
            progress=0,
            status_note=WAITING_NOTE,
            created_by=room.host_id,  # chủ phòng = "người tải cuộc họp lên" → được duyệt đầu việc
        )
        db.add(meeting)
        db.flush()
        room.meeting_id = meeting.id
        for t in room.tracks:
            t.meeting_id = meeting.id
    else:
        room.finalized = True  # không có gì để nhận dạng
    db.flush()

    try:
        lk.get_livekit().delete_room(room.code)  # ngắt kết nối mọi người còn trong phòng
    except lk.LiveKitError as e:
        log.warning("Không đóng được phòng LiveKit %s: %s", room.code, e)
    return meeting


def try_finalize(db: Session, room: MeetingRoom) -> bool:
    """Phòng đã kết thúc: đủ ghi âm của mọi người (hoặc đã chờ hết 2 phút) thì đưa vào hàng đợi
    nhận dạng. Trả về True nếu vừa chốt."""
    if room.status != RoomStatus.ENDED or room.finalized or room.meeting_id is None:
        return False
    waited = (now_utc() - room.ended_at).total_seconds() if room.ended_at else 0
    all_in = all(t.finished for t in room.tracks)
    if not all_in and waited < get_settings().ROOM_UPLOAD_WAIT_SEC:
        return False

    meeting = db.get(Meeting, room.meeting_id)
    room.finalized = True
    if meeting is None:  # cuộc họp đã bị xóa trong lúc chờ
        db.flush()
        return True
    meeting.status_note = None
    if not any(t.size > 0 for t in room.tracks):
        meeting.status = MeetingStatus.FAILED
        meeting.error = "Không nhận được ghi âm của ai (không ai bật mic, hoặc trình duyệt chưa gửi kịp)."
    else:
        meeting_service.enqueue_transcription(meeting)
    db.flush()
    return True


def delete_track_files(room_ids: list[int]) -> None:
    for rid in room_ids:
        shutil.rmtree(meeting_service.upload_root() / "rooms" / str(rid), ignore_errors=True)


# ---------- Tác vụ nền: tự đóng phòng trống, chốt phòng đã kết thúc ----------


def _close_idle_room(db: Session, room: MeetingRoom, why: str) -> None:
    log.info("Phòng %s %s → tự đóng", room.code, why)
    meeting = end_room(db, room)
    db.commit()
    notify_room(room)
    if meeting:
        meeting_service.notify_meeting(meeting)


def reconcile(db: Session) -> None:
    """Chạy định kỳ trong backend (xem app/main.py).

    Với phòng đang mở:
      - Mọi người rời hết quá ROOM_EMPTY_CLOSE_SEC (30 giây) → tự đóng.
        Phòng vừa tạo mà CHƯA ai vào được (lỗi kết nối…) → đóng sau ROOM_UNJOINED_CLOSE_SEC (1 phút).
      - Còn người nhưng chủ phòng vắng quá ROOM_HOST_ABSENT_SEC (1 phút: mất mạng, mất điện…)
        → nhượng quyền chủ phòng cho người vào sớm nhất còn lại.
    Với phòng đã kết thúc: thử chốt ghi âm (đủ ghi âm / hết thời gian chờ).
    """
    s = get_settings()
    now = now_utc()
    for room in db.scalars(select(MeetingRoom).where(MeetingRoom.status == RoomStatus.OPEN)).all():
        try:
            inside = lk.get_livekit().participant_ids(room.code)
        except lk.LiveKitError:
            continue  # LiveKit tạm không trả lời → không vội kết luận phòng trống
        if inside:
            changed = False
            if room.empty_since is not None:
                room.empty_since, changed = None, True
            if room.first_joined_at is None:
                room.first_joined_at, changed = now, True
            if room.host_id in inside:
                if room.host_absent_since is not None:  # chủ phòng đã vào lại kịp → vẫn là chủ phòng
                    room.host_absent_since, changed = None, True
            elif room.host_absent_since is None:
                room.host_absent_since, changed = now, True
            elif (now - room.host_absent_since).total_seconds() >= s.ROOM_HOST_ABSENT_SEC:
                log.info("Phòng %s: chủ phòng vắng quá lâu → nhượng quyền cho user %s", room.code, inside[0])
                transfer_host(db, room, inside[0])
                db.commit()
                notify_room(room)
                continue
            if changed:
                db.commit()
            continue

        # --- Không còn ai trong phòng ---
        if room.first_joined_at is None:  # vừa tạo, người mở chưa kịp lấy vé (hoặc lấy vé bị lỗi)
            if (now - room.created_at).total_seconds() >= s.ROOM_UNJOINED_CLOSE_SEC:
                _close_idle_room(db, room, "mở ra mà không ai vào")
            continue
        if room.empty_since is None:
            room.empty_since = now
            db.commit()
        elif (now - room.empty_since).total_seconds() >= s.ROOM_EMPTY_CLOSE_SEC:
            _close_idle_room(db, room, "không còn ai")

    pending = db.scalars(
        select(MeetingRoom).where(MeetingRoom.status == RoomStatus.ENDED, MeetingRoom.finalized.is_(False))
    ).all()
    for room in pending:
        if try_finalize(db, room):
            db.commit()
            meeting = db.get(Meeting, room.meeting_id) if room.meeting_id else None
            if meeting:
                meeting_service.notify_meeting(meeting)
