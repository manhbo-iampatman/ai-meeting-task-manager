"""Giai đoạn 6 — phòng họp trực tuyến "Online Meeting".

Hình và tiếng KHÔNG đi qua các API này (chúng đi thẳng giữa trình duyệt và LiveKit). Ở đây chỉ có:
mở / vào / kết thúc phòng, bật / dừng ghi âm, và nhận ghi âm của từng người gửi lên từng khúc.
"""

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import DB, CurrentUser, get_membership
from app.core.realtime import publish_event, workspace_room
from app.models import Meeting, MeetingRoom, User, Workspace
from app.schemas.room import RoomCreate, RoomEndOut, RoomJoinOut, RoomOut, TrackCreate, TrackOut
from app.services import meeting_service
from app.services import room_service as svc

router = APIRouter(tags=["rooms"])


def _out(db: DB, room: MeetingRoom, user: User) -> RoomOut:
    out = RoomOut.model_validate(room)
    ws = db.get(Workspace, room.workspace_id)
    out.workspace_name = ws.name if ws else ""
    out.owner_id = ws.owner_id if ws else None
    out.is_member = svc.is_member(db, room.workspace_id, user.id)
    out.is_host = room.host_id == user.id
    out.can_control = svc.can_control(db, room, user)
    return out


@router.get("/workspaces/{workspace_id}/room", response_model=RoomOut | None)
def get_open_room(workspace_id: int, user: CurrentUser, db: DB):
    """Phòng đang mở của nhóm (null = chưa có) → trang nhóm hiện "Online Meeting" hay "Tham gia phòng"."""
    get_membership(db, workspace_id, user)
    room = svc.get_open_room(db, workspace_id)
    return _out(db, room, user) if room else None


@router.post("/workspaces/{workspace_id}/room", response_model=RoomOut)
def open_room(workspace_id: int, data: RoomCreate, user: CurrentUser, db: DB):
    """Mở phòng (thành viên nào cũng mở được). Nhóm đang có phòng mở → trả về phòng đó."""
    get_membership(db, workspace_id, user)
    room, created = svc.open_room(db, workspace_id, user, data.title)
    db.commit()
    db.refresh(room)
    if created:
        svc.notify_room(room)
    return _out(db, room, user)


@router.get("/rooms/{code}", response_model=RoomOut)
def get_room(code: str, user: CurrentUser, db: DB):
    """Xem thông tin phòng qua link. Người có link (đã đăng nhập) xem được dù chưa ở trong nhóm."""
    return _out(db, svc.get_room_by_code(db, code), user)


@router.post("/rooms/{code}/join", response_model=RoomJoinOut)
def join_room(code: str, user: CurrentUser, db: DB):
    """Lấy vé vào phòng. Chưa ở trong nhóm → tự vào nhóm rồi vào phòng (như Google Meet)."""
    room = svc.get_room_by_code(db, code)
    token, joined = svc.join_room(db, room, user)
    db.commit()
    if joined:  # trang nhóm của người khác cập nhật danh sách thành viên
        publish_event(workspace_room(room.workspace_id), {"type": "members_updated"})
    return RoomJoinOut(room=_out(db, room, user), token=token, joined_workspace=joined)


def _controlled_room(db: DB, code: str, user: User) -> MeetingRoom:
    room = svc.get_room_by_code(db, code)
    get_membership(db, room.workspace_id, user)
    svc.require_control(db, room, user)
    return room


@router.post("/rooms/{code}/recording/start", response_model=RoomOut)
def start_recording(code: str, user: CurrentUser, db: DB):
    """Chủ phòng bấm "Bắt đầu ghi" → mọi trình duyệt trong phòng tự ghi mic của mình."""
    room = _controlled_room(db, code, user)
    svc.start_recording(db, room)
    db.commit()
    svc.notify_room(room)
    return _out(db, room, user)


@router.post("/rooms/{code}/recording/stop", response_model=RoomOut)
def stop_recording(code: str, user: CurrentUser, db: DB):
    room = _controlled_room(db, code, user)
    svc.stop_recording(db, room)
    db.commit()
    svc.notify_room(room)
    return _out(db, room, user)


@router.post("/rooms/{code}/leave", response_model=RoomEndOut)
def leave_room(code: str, user: CurrentUser, db: DB):
    """Bấm "Rời phòng" (chỉ mình tôi rời). Nếu người rời là CHỦ PHÒNG: phòng còn người thì nhượng
    quyền ngay cho người vào sớm nhất còn lại; không còn ai thì buổi họp kết thúc."""
    room = svc.get_room_by_code(db, code)
    get_membership(db, room.workspace_id, user)
    was_host = room.host_id == user.id
    meeting = svc.leave_room(db, room, user)
    svc.try_finalize(db, room)
    db.commit()
    db.refresh(room)  # nạp lại thông tin chủ phòng mới
    if was_host:
        svc.notify_room(room)
    if meeting:
        db.refresh(meeting)
        meeting_service.notify_meeting(meeting)
    return RoomEndOut(room=_out(db, room, user), meeting_id=room.meeting_id)


@router.post("/rooms/{code}/end", response_model=RoomEndOut)
def end_room(code: str, user: CurrentUser, db: DB):
    """"Kết thúc cho mọi người". Có ghi âm → sinh ra một cuộc họp trong danh sách của nhóm."""
    room = _controlled_room(db, code, user)
    meeting = svc.end_room(db, room)
    svc.try_finalize(db, room)  # không ai còn đang gửi ghi âm thì xử lý luôn, khỏi chờ
    db.commit()
    svc.notify_room(room)
    if meeting:
        db.refresh(meeting)
        meeting_service.notify_meeting(meeting)
    return RoomEndOut(room=_out(db, room, user), meeting_id=room.meeting_id)


# ---------- Ghi âm của từng người ----------


@router.post("/rooms/{code}/tracks", response_model=TrackOut, status_code=status.HTTP_201_CREATED)
def create_track(code: str, data: TrackCreate, user: CurrentUser, db: DB):
    room = svc.get_room_by_code(db, code)
    get_membership(db, room.workspace_id, user)
    track = svc.create_track(db, room, user, data.mime, data.elapsed_ms)
    db.commit()
    return TrackOut(track_id=track.id, next_seq=track.next_seq)


@router.put("/room-tracks/{track_id}/chunks/{seq}", response_model=TrackOut)
async def upload_chunk(track_id: int, seq: int, request: Request, user: CurrentUser, db: DB):
    """Nhận một khúc ghi âm (dữ liệu thô trong thân request). Vẫn nhận sau khi phòng đã kết thúc
    — đó là phần "đến muộn" của người rớt mạng."""
    if int(request.headers.get("content-length") or 0) > svc.MAX_CHUNK_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Khúc ghi âm quá lớn")
    data = await request.body()
    next_seq = svc.append_chunk(db, track_id, user, seq, data)
    db.commit()
    return TrackOut(track_id=track_id, next_seq=next_seq)


@router.post("/room-tracks/{track_id}/finish", response_model=TrackOut)
def finish_track(track_id: int, user: CurrentUser, db: DB):
    """Trình duyệt báo đã gửi hết ghi âm của mình."""
    track = svc.finish_track(db, track_id, user)
    room = track.room
    late = room.finalized and track.meeting_id is not None and track.has_new_audio
    if not late:
        svc.try_finalize(db, room)  # người cuối cùng gửi xong → xử lý luôn, khỏi chờ đủ 2 phút
    db.commit()
    if late:  # cuộc họp đã được nhận dạng mà không có phần này → nhận dạng bổ sung
        meeting_service.enqueue_late_track(track.id)
    elif room.finalized and room.meeting_id:
        meeting = db.get(Meeting, room.meeting_id)
        if meeting:
            meeting_service.notify_meeting(meeting)
    return TrackOut(track_id=track.id, next_seq=track.next_seq)
