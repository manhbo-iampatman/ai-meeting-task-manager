"""Test Giai đoạn 6 — phòng họp trực tuyến "Online Meeting".

Không cần Docker / GPU / trình duyệt: LiveKit, Whisper và LLM đều được thay bằng bản GIẢ.
Thứ được kiểm tra là phần MeetFlow tự viết: quyền, vòng đời phòng, nhận ghi âm từng khúc,
ghép bản ghi có tên người nói, lọc tiếng vọng, bổ sung ghi âm đến muộn, giao việc cho người nói.
"""

from datetime import date, timedelta

import jwt
import pytest

from app.ai.extraction import extract_meeting
from app.ai.postprocess import speaker_merge
from app.ai.postprocess.name_matching import MemberInfo
from app.ai.stt.base import Segment, TranscriptResult
from app.core import livekit as lk
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Meeting, MeetingRoom, MeetingStatus, MeetingTrack
from app.services import meeting_service, room_service
from app.workers import online_jobs
from tests.conftest import auth, register


class FakeLiveKit:
    """LiveKit giả: nhớ phòng nào đang mở và ai đang ở trong."""

    def __init__(self):
        self.rooms: dict[str, dict] = {}
        self.inside: dict[str, list[int]] = {}
        self.down = False

    def _check(self):
        if self.down:
            raise lk.LiveKitError("LiveKit chưa bật")

    def create_room(self, name, metadata):
        self._check()
        self.rooms[name] = metadata
        self.inside[name] = []

    def delete_room(self, name):
        self._check()
        self.rooms.pop(name, None)
        self.inside.pop(name, None)

    def participant_ids(self, name):
        self._check()
        return list(self.inside[name]) if name in self.rooms else None

    def set_metadata(self, name, metadata):
        self._check()
        self.rooms[name] = metadata


@pytest.fixture(autouse=True)
def fake_livekit(monkeypatch):
    fake = FakeLiveKit()
    monkeypatch.setattr(lk, "get_livekit", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch):
    """Không đẩy job thật lên Redis: ghi lại để test tự chạy job."""
    queued = {"meetings": [], "late": []}

    def fake_enqueue(meeting):
        queued["meetings"].append(meeting.id)
        meeting.status, meeting.progress, meeting.error, meeting.status_note = MeetingStatus.QUEUED, 0, None, None

    monkeypatch.setattr(meeting_service, "enqueue_transcription", fake_enqueue)
    monkeypatch.setattr(meeting_service, "enqueue_late_track", lambda track_id, force=False: queued["late"].append((track_id, force)))
    return queued


class FakeSTT:
    """Whisper giả: mỗi file ghi âm chứa sẵn "kịch bản" dạng `giây_đầu|giây_cuối|câu nói` mỗi dòng."""

    name = "fake-whisper"

    def transcribe(self, audio_path, language="vi", on_progress=None, initial_prompt=None):
        segs = []
        with open(audio_path, encoding="utf-8") as f:
            for line in f.read().splitlines():
                if line.count("|") == 2:
                    a, b, text = line.split("|")
                    segs.append(Segment(float(a), float(b), text))
        if on_progress:
            on_progress(1.0)
        return TranscriptResult(
            text=" ".join(s.text for s in segs), segments=segs, language="vi",
            duration_sec=max((s.end for s in segs), default=0.0), processing_sec=0.1, model=self.name,
        )


@pytest.fixture
def fake_ai(monkeypatch):
    monkeypatch.setattr(online_jobs, "get_stt_provider", lambda: FakeSTT())
    # Không giải mã âm thanh thật: không có số đo âm lượng, không ghi file trộn
    monkeypatch.setattr(online_jobs.audio_mix, "load_audio", lambda path: None)
    monkeypatch.setattr(online_jobs.audio_mix, "segments_rms", lambda path, intervals: [None] * len(intervals))
    monkeypatch.setattr(online_jobs.audio_mix, "mix_files", lambda sources, dest: (False, 0.0))


def _setup(client):
    nam = register(client, "nam@example.com", "Nguyễn Văn Nam")
    lan = register(client, "lan@example.com", "Trần Thị Lan")
    ws = client.post("/api/workspaces", json={"name": "Nhóm KLTN"}, headers=auth(nam)).json()
    client.post("/api/workspaces/join", json={"invite_code": ws["invite_code"]}, headers=auth(lan))
    return nam, lan, ws


def _open(client, who, ws):
    r = client.post(f"/api/workspaces/{ws['id']}/room", json={}, headers=auth(who))
    assert r.status_code == 200, r.text
    return r.json()


def _record(client, who, code, script: str, elapsed_ms=0, finish=True) -> int:
    """Giả làm trình duyệt: mở track, gửi "ghi âm" thành 2 khúc, báo xong."""
    r = client.post(f"/api/rooms/{code}/tracks", json={"mime": "audio/webm", "elapsed_ms": elapsed_ms}, headers=auth(who))
    assert r.status_code == 201, r.text
    tid = r.json()["track_id"]
    data = script.encode("utf-8")
    half = len(data) // 2
    for seq, part in enumerate([data[:half], data[half:]]):
        r = client.put(f"/api/room-tracks/{tid}/chunks/{seq}", content=part, headers=auth(who))
        assert r.status_code == 200 and r.json()["next_seq"] == seq + 1, r.text
    if finish:
        assert client.post(f"/api/room-tracks/{tid}/finish", headers=auth(who)).status_code == 200
    return tid


# ---------- Mở phòng, vào phòng ----------


def test_one_open_room_per_workspace(client, fake_livekit):
    nam, lan, ws = _setup(client)
    assert client.get(f"/api/workspaces/{ws['id']}/room", headers=auth(nam)).json() is None

    room = _open(client, lan, ws)  # thành viên nào cũng mở được phòng
    assert room["status"] == "open" and room["is_host"] and room["host"]["full_name"] == "Trần Thị Lan"
    assert room["title"].startswith("Online Meeting ") and room["recording"] == "idle"
    assert room["code"] in fake_livekit.rooms

    # Người vào sau bấm nút → nhận đúng phòng đang mở, không tạo phòng thứ hai
    again = _open(client, nam, ws)
    assert again["code"] == room["code"] and not again["is_host"]
    assert again["can_control"]  # Nam là trưởng nhóm → vẫn được dừng ghi / kết thúc phòng
    assert client.get(f"/api/workspaces/{ws['id']}/room", headers=auth(nam)).json()["code"] == room["code"]
    with SessionLocal() as db:
        assert db.query(MeetingRoom).count() == 1

    # Kết thúc phòng → buổi sau là phòng MỚI, link MỚI
    assert client.post(f"/api/rooms/{room['code']}/end", headers=auth(lan)).status_code == 200
    assert client.get(f"/api/workspaces/{ws['id']}/room", headers=auth(nam)).json() is None
    assert _open(client, nam, ws)["code"] != room["code"]


def test_join_gives_livekit_token(client):
    nam, lan, ws = _setup(client)
    room = _open(client, nam, ws)
    r = client.post(f"/api/rooms/{room['code']}/join", headers=auth(lan))
    assert r.status_code == 200 and r.json()["joined_workspace"] is False
    s = get_settings()
    claims = jwt.decode(r.json()["token"], s.LIVEKIT_API_SECRET, algorithms=["HS256"])
    assert claims["iss"] == s.LIVEKIT_API_KEY and claims["sub"] == str(lan["_user"]["id"])
    assert claims["name"] == "Trần Thị Lan"
    assert claims["video"]["room"] == room["code"] and claims["video"]["roomJoin"] and claims["video"]["canPublish"]
    assert claims["video"]["canUpdateOwnMetadata"] is True  # giơ tay = tự đặt thuộc tính của chính mình


def test_room_link_adds_outsider_to_workspace(client):
    """Link phòng hoạt động như Google Meet: đăng nhập xong là tự vào nhóm rồi vào phòng."""
    nam, lan, ws = _setup(client)
    room = _open(client, nam, ws)
    minh = register(client, "minh@example.com", "Lê Văn Minh")

    info = client.get(f"/api/rooms/{room['code']}", headers=auth(minh)).json()
    assert info["workspace_name"] == "Nhóm KLTN" and info["is_member"] is False

    r = client.post(f"/api/rooms/{room['code']}/join", headers=auth(minh))
    assert r.status_code == 200 and r.json()["joined_workspace"] is True and r.json()["room"]["is_member"]
    members = client.get(f"/api/workspaces/{ws['id']}", headers=auth(nam)).json()["members"]
    assert {m["user"]["full_name"] for m in members} == {"Nguyễn Văn Nam", "Trần Thị Lan", "Lê Văn Minh"}

    assert client.get("/api/rooms/khong-co-ma-nay", headers=auth(minh)).status_code == 404
    assert client.get(f"/api/rooms/{room['code']}").status_code == 401  # bắt buộc đăng nhập


def test_room_is_limited_to_six_people(client, fake_livekit):
    nam, lan, ws = _setup(client)
    room = _open(client, nam, ws)
    fake_livekit.inside[room["code"]] = [101, 102, 103, 104, 105, nam["_user"]["id"]]
    r = client.post(f"/api/rooms/{room['code']}/join", headers=auth(lan))
    assert r.status_code == 409 and "đủ 6 người" in r.json()["detail"]
    # Người đang ở trong phòng (tải lại trang) thì vẫn lấy được vé
    assert client.post(f"/api/rooms/{room['code']}/join", headers=auth(nam)).status_code == 200


def test_livekit_down_is_reported_clearly(client, fake_livekit):
    nam, _, ws = _setup(client)
    fake_livekit.down = True
    r = client.post(f"/api/workspaces/{ws['id']}/room", json={}, headers=auth(nam))
    assert r.status_code == 503 and "docker compose up -d" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.query(MeetingRoom).count() == 0  # không để lại phòng "ma"


# ---------- Ghi âm ----------


def test_recording_is_one_run_and_only_host_or_owner_controls_it(client, fake_livekit):
    nam, lan, ws = _setup(client)
    minh = register(client, "minh@example.com", "Lê Văn Minh")
    client.post("/api/workspaces/join", json={"invite_code": ws["invite_code"]}, headers=auth(minh))
    room = _open(client, lan, ws)  # Lan là chủ phòng, Nam là trưởng nhóm, Minh là thành viên thường
    code = room["code"]

    assert client.post(f"/api/rooms/{code}/recording/start", headers=auth(minh)).status_code == 403
    # Chưa ghi âm thì chưa nhận ghi âm của ai
    assert client.post(f"/api/rooms/{code}/tracks", json={}, headers=auth(minh)).status_code == 409

    r = client.post(f"/api/rooms/{code}/recording/start", headers=auth(lan))
    assert r.status_code == 200 and r.json()["recording"] == "on"
    assert fake_livekit.rooms[code]["recording"] == "on"  # mọi trình duyệt trong phòng được báo qua LiveKit
    assert client.post(f"/api/rooms/{code}/recording/start", headers=auth(lan)).status_code == 409

    # Trưởng nhóm cũng dừng được (chủ phòng có thể đã rớt mạng)
    r = client.post(f"/api/rooms/{code}/recording/stop", headers=auth(nam))
    assert r.status_code == 200 and r.json()["recording"] == "stopped"
    # Ghi một mạch: đã dừng thì buổi đó không ghi lại
    r = client.post(f"/api/rooms/{code}/recording/start", headers=auth(lan))
    assert r.status_code == 409 and "không ghi lại được" in r.json()["detail"]
    assert client.post(f"/api/rooms/{code}/end", headers=auth(minh)).status_code == 403


def test_room_without_recording_creates_no_meeting(client):
    nam, _, ws = _setup(client)
    room = _open(client, nam, ws)
    r = client.post(f"/api/rooms/{room['code']}/end", headers=auth(nam))
    assert r.status_code == 200 and r.json()["meeting_id"] is None and r.json()["room"]["status"] == "ended"
    assert client.get(f"/api/workspaces/{ws['id']}/meetings", headers=auth(nam)).json() == []
    # Link của buổi đã kết thúc hết dùng được
    assert client.post(f"/api/rooms/{room['code']}/join", headers=auth(nam)).status_code == 410


def test_chunk_upload_is_ordered_and_idempotent(client):
    nam, lan, ws = _setup(client)
    code = _open(client, nam, ws)["code"]
    client.post(f"/api/rooms/{code}/recording/start", headers=auth(nam))
    tid = client.post(f"/api/rooms/{code}/tracks", json={"mime": "audio/webm"}, headers=auth(nam)).json()["track_id"]
    url = f"/api/room-tracks/{tid}/chunks"

    assert client.put(f"{url}/0", content=b"AAAA", headers=auth(nam)).json()["next_seq"] == 1
    # Mạng chập chờn, trình duyệt gửi lại khúc 0 → không bị nối hai lần
    assert client.put(f"{url}/0", content=b"AAAA", headers=auth(nam)).json()["next_seq"] == 1
    # Gửi nhảy cóc → từ chối, cho biết đang chờ khúc nào
    r = client.put(f"{url}/2", content=b"CCCC", headers=auth(nam))
    assert r.status_code == 409 and r.json()["detail"] == {"expected_seq": 1}
    assert client.put(f"{url}/1", content=b"BBBB", headers=auth(nam)).json()["next_seq"] == 2
    # Người khác không ghi được vào track của mình
    assert client.put(f"{url}/2", content=b"XXXX", headers=auth(lan)).status_code == 404
    assert client.put(f"{url}/2", content=b"", headers=auth(nam)).status_code == 400

    with SessionLocal() as db:
        t = db.get(MeetingTrack, tid)
        assert t.size == 8 and room_service.track_abspath(t).read_bytes() == b"AAAABBBB"
        assert t.speaker_name == "Nguyễn Văn Nam" and not t.finished


# ---------- Kết thúc phòng → cuộc họp → bản ghi có tên người nói ----------


def test_end_waits_for_everyones_audio_then_queues(client, fake_queue, monkeypatch):
    nam, lan, ws = _setup(client)
    code = _open(client, nam, ws)["code"]
    client.post(f"/api/rooms/{code}/recording/start", headers=auth(nam))
    _record(client, nam, code, "0|2|Chào mọi người.")
    lan_track = _record(client, lan, code, "3|5|Em chào anh.", finish=False)  # Lan chưa gửi xong

    r = client.post(f"/api/rooms/{code}/end", headers=auth(nam))
    mid = r.json()["meeting_id"]
    assert mid is not None and fake_queue["meetings"] == []
    d = client.get(f"/api/meetings/{mid}", headers=auth(lan)).json()
    assert d["source_type"] == "online" and d["status"] == "uploaded" and "chờ ghi âm" in d["status_note"]
    assert d["created_by"] == nam["_user"]["id"]  # chủ phòng = người "tải cuộc họp lên"
    assert [t["finished"] for t in d["tracks"]] == [True, False]

    # Chưa hết thời gian chờ → tác vụ nền chưa chốt
    with SessionLocal() as db:
        room_service.reconcile(db)
    assert fake_queue["meetings"] == []

    # Lan gửi xong → chốt ngay, không chờ đủ 2 phút
    client.post(f"/api/room-tracks/{lan_track}/finish", headers=auth(lan))
    assert fake_queue["meetings"] == [mid]
    assert client.get(f"/api/meetings/{mid}", headers=auth(nam)).json()["status"] == "queued"


def test_end_stops_waiting_after_timeout(client, fake_queue, monkeypatch):
    nam, lan, ws = _setup(client)
    code = _open(client, nam, ws)["code"]
    client.post(f"/api/rooms/{code}/recording/start", headers=auth(nam))
    _record(client, nam, code, "0|2|Chào mọi người.")
    _record(client, lan, code, "3|5|Em chào anh.", finish=False)  # Lan rớt mạng, không báo xong
    mid = client.post(f"/api/rooms/{code}/end", headers=auth(nam)).json()["meeting_id"]

    with SessionLocal() as db:  # giả lập đã qua 2 phút
        room = db.query(MeetingRoom).one()
        room.ended_at -= timedelta(seconds=get_settings().ROOM_UPLOAD_WAIT_SEC + 1)
        db.commit()
        room_service.reconcile(db)
    assert fake_queue["meetings"] == [mid]


def test_online_job_builds_speaker_transcript(client, fake_queue, fake_ai):
    nam, lan, ws = _setup(client)
    code = _open(client, nam, ws)["code"]
    client.post(f"/api/rooms/{code}/recording/start", headers=auth(nam))
    _record(client, nam, code, "0|3|Chào mọi người, mình bắt đầu họp nhé.\n10|14|Ai nhận phần slide thuyết trình?")
    # Lan vào muộn 12 giây: máy ghi của Lan bắt đầu sau lúc bấm "Bắt đầu ghi" → mốc thời gian phải được dời
    lan_track = _record(client, lan, code, "0.5|4|Dạ phần slide để em làm ạ.")
    with SessionLocal() as db:
        db.get(MeetingTrack, lan_track).started_at += timedelta(seconds=12)
        db.commit()
    mid = client.post(f"/api/rooms/{code}/end", headers=auth(nam)).json()["meeting_id"]
    assert fake_queue["meetings"] == [mid]

    res = online_jobs.process_online_meeting_job(mid)
    assert res["tracks"] == 2 and res["segments"] == 3 and res["errors"] == []

    d = client.get(f"/api/meetings/{mid}", headers=auth(lan)).json()
    assert d["status"] == "transcribed" and d["can_review"] is False  # Lan không phải chủ phòng / trưởng nhóm
    segs = d["transcript"]["segments"]
    assert [s["speaker"] for s in segs] == ["Nguyễn Văn Nam", "Nguyễn Văn Nam", "Trần Thị Lan"]
    assert segs[2]["speaker_id"] == lan["_user"]["id"] and segs[2]["track_id"] == lan_track
    assert 12.0 <= segs[2]["start"] <= 13.5  # 0.5s trong file của Lan + ~12s vào muộn
    assert d["transcript"]["full_text"].splitlines()[2] == "Trần Thị Lan: Dạ phần slide để em làm ạ."
    assert all(t["merged"] and not t["pending"] for t in d["tracks"])
    assert client.get(f"/api/meetings/{mid}", headers=auth(nam)).json()["can_review"] is True

    # Sửa chữ trong bản ghi KHÔNG làm mất thông tin ai nói
    segs[2]["text"] = "Dạ, phần slide để em làm ạ."
    d = client.put(f"/api/meetings/{mid}/transcript", json={"segments": segs}, headers=auth(nam)).json()
    assert d["transcript"]["segments"][2]["speaker"] == "Trần Thị Lan"
    assert d["transcript"]["full_text"].endswith("Trần Thị Lan: Dạ, phần slide để em làm ạ.")


def test_nobody_spoke_is_reported(client, fake_ai):
    nam, _, ws = _setup(client)
    code = _open(client, nam, ws)["code"]
    client.post(f"/api/rooms/{code}/recording/start", headers=auth(nam))
    _record(client, nam, code, "(mic tắt suốt buổi)")
    mid = client.post(f"/api/rooms/{code}/end", headers=auth(nam)).json()["meeting_id"]
    res = online_jobs.process_online_meeting_job(mid)
    assert "Không nhận ra lời nói" in res.get("error", ""), res
    assert client.get(f"/api/meetings/{mid}", headers=auth(nam)).json()["status"] == "failed"


def test_late_audio_is_added_automatically_or_waits_for_reviewer(client, fake_queue, fake_ai):
    nam, lan, ws = _setup(client)
    code = _open(client, nam, ws)["code"]
    client.post(f"/api/rooms/{code}/recording/start", headers=auth(nam))
    _record(client, nam, code, "0|3|Lan ơi phần slide em làm nhé.")
    # Lan rớt mạng: mới gửi được khúc đầu, chưa có câu nào trọn vẹn
    lan_track = client.post(f"/api/rooms/{code}/tracks", json={}, headers=auth(lan)).json()["track_id"]
    client.put(f"/api/room-tracks/{lan_track}/chunks/0", content="(đầu file)\n".encode(), headers=auth(lan))
    mid = client.post(f"/api/rooms/{code}/end", headers=auth(nam)).json()["meeting_id"]
    with SessionLocal() as db:  # hết 2 phút chờ → nhận dạng với phần đã có
        room = db.query(MeetingRoom).one()
        room.ended_at -= timedelta(seconds=get_settings().ROOM_UPLOAD_WAIT_SEC + 1)
        db.commit()
        room_service.reconcile(db)
    online_jobs.process_online_meeting_job(mid)
    d = client.get(f"/api/meetings/{mid}", headers=auth(nam)).json()
    assert len(d["transcript"]["segments"]) == 1
    assert [(t["speaker_name"], t["finished"]) for t in d["tracks"]] == [("Nguyễn Văn Nam", True), ("Trần Thị Lan", False)]

    # Lan có mạng lại, trình duyệt gửi nốt → hệ thống nhận dạng bổ sung
    client.put(f"/api/room-tracks/{lan_track}/chunks/1", content="4|7|Dạ vâng để em làm ạ.\n".encode(), headers=auth(lan))
    client.post(f"/api/room-tracks/{lan_track}/finish", headers=auth(lan))
    assert fake_queue["late"] == [(lan_track, False)]
    # Bản ghi chưa ai sửa, chưa tóm tắt → TỰ bổ sung
    assert online_jobs.process_late_track_job(lan_track)["merged"] is True
    d = client.get(f"/api/meetings/{mid}", headers=auth(nam)).json()
    assert [s["speaker"] for s in d["transcript"]["segments"]] == ["Nguyễn Văn Nam", "Trần Thị Lan"]
    assert all(t["merged"] for t in d["tracks"])

    # --- Trường hợp bản ghi ĐÃ bị sửa tay: không tự ghi đè, chờ người duyệt bấm ---
    segs = d["transcript"]["segments"]
    segs[0]["text"] = "Lan ơi, phần slide em làm nhé."
    client.put(f"/api/meetings/{mid}/transcript", json={"segments": segs}, headers=auth(nam))
    with SessionLocal() as db:  # thêm một đoạn nữa về muộn
        t = db.get(MeetingTrack, lan_track)
        with room_service.track_abspath(t).open("ab") as f:
            f.write("9|12|Thứ Sáu em gửi ạ.\n".encode())
        t.size += 30
        db.commit()
    assert online_jobs.process_late_track_job(lan_track) == {"pending": True}
    d = client.get(f"/api/meetings/{mid}", headers=auth(nam)).json()
    assert len(d["transcript"]["segments"]) == 2
    assert [t["pending"] for t in d["tracks"]] == [False, True]

    # Chỉ người duyệt được bấm "Bổ sung"
    assert client.post(f"/api/meetings/{mid}/tracks/{lan_track}/merge", headers=auth(lan)).status_code == 403
    assert client.post(f"/api/meetings/{mid}/tracks/{lan_track}/merge", headers=auth(nam)).status_code == 200
    assert fake_queue["late"][-1] == (lan_track, True)
    assert online_jobs.process_late_track_job(lan_track, force=True)["merged"] is True
    d = client.get(f"/api/meetings/{mid}", headers=auth(nam)).json()
    texts = [s["text"] for s in d["transcript"]["segments"]]
    assert texts == ["Lan ơi, phần slide em làm nhé.", "Dạ vâng để em làm ạ.", "Thứ Sáu em gửi ạ."]  # chỗ Nam sửa tay vẫn còn
    assert d["transcript"]["edited"] is True and not any(t["pending"] for t in d["tracks"])


def test_empty_room_closes_itself(client, fake_livekit, fake_queue, monkeypatch):
    nam, _, ws = _setup(client)
    code = _open(client, nam, ws)["code"]
    client.post(f"/api/rooms/{code}/recording/start", headers=auth(nam))
    _record(client, nam, code, "0|2|Chào mọi người.")
    fake_livekit.inside[code] = [nam["_user"]["id"]]

    with SessionLocal() as db:
        room_service.reconcile(db)  # còn người → không làm gì
        assert db.query(MeetingRoom).one().empty_since is None
        fake_livekit.inside[code] = []  # mọi người rời hết
        room_service.reconcile(db)
        room = db.query(MeetingRoom).one()
        assert room.status == "open" and room.empty_since is not None  # mới trống → chưa đóng vội
        room.empty_since -= timedelta(seconds=get_settings().ROOM_EMPTY_CLOSE_SEC + 1)
        db.commit()
        room_service.reconcile(db)  # trống quá 3 phút → tự đóng, tạo cuộc họp, đưa đi nhận dạng
        db.refresh(room)
        assert room.status == "ended" and room.recording == "stopped" and room.finalized
        assert fake_queue["meetings"] == [room.meeting_id]
    assert code not in fake_livekit.rooms


def test_deleting_meeting_removes_track_files(client, fake_ai):
    nam, _, ws = _setup(client)
    code = _open(client, nam, ws)["code"]
    client.post(f"/api/rooms/{code}/recording/start", headers=auth(nam))
    tid = _record(client, nam, code, "0|2|Chào mọi người.")
    mid = client.post(f"/api/rooms/{code}/end", headers=auth(nam)).json()["meeting_id"]
    with SessionLocal() as db:
        path = room_service.track_abspath(db.get(MeetingTrack, tid))
    assert path.exists()
    assert client.delete(f"/api/meetings/{mid}", headers=auth(nam)).status_code == 204
    assert not path.exists()
    with SessionLocal() as db:
        assert db.get(Meeting, mid) is None and db.get(MeetingTrack, tid) is None


# ---------- Chủ phòng rời phòng / vắng mặt (quyết định 18/11/2026, sau khi thử 2 máy) ----------


def _three(client):
    """Nam = trưởng nhóm, Lan = người mở phòng (chủ phòng), Minh = thành viên thường."""
    nam, lan, ws = _setup(client)
    minh = register(client, "minh@example.com", "Lê Văn Minh")
    client.post("/api/workspaces/join", json={"invite_code": ws["invite_code"]}, headers=auth(minh))
    room = _open(client, lan, ws)
    return nam, lan, minh, ws, room["code"]


def _info(client, who, code):
    return client.get(f"/api/rooms/{code}", headers=auth(who)).json()


def test_host_leaving_hands_over_to_earliest_joiner(client, fake_livekit):
    nam, lan, minh, ws, code = _three(client)
    ids = {k: v["_user"]["id"] for k, v in {"nam": nam, "lan": lan, "minh": minh}.items()}
    fake_livekit.inside[code] = [ids["lan"], ids["minh"], ids["nam"]]  # thứ tự vào phòng
    assert _info(client, nam, code)["owner_id"] == ids["nam"]  # để giao diện hiện nhãn "Trưởng nhóm"

    # Người thường bấm rời phòng → không đổi gì
    assert client.post(f"/api/rooms/{code}/leave", headers=auth(minh)).status_code == 200
    assert _info(client, lan, code)["is_host"] is True

    # Chủ phòng chọn "Chỉ mình tôi rời" → quyền chuyển NGAY cho người vào sớm nhất còn lại (Minh)
    r = client.post(f"/api/rooms/{code}/leave", headers=auth(lan))
    assert r.status_code == 200 and r.json()["room"]["status"] == "open"
    assert r.json()["room"]["host"]["full_name"] == "Lê Văn Minh"
    assert fake_livekit.rooms[code]["host_id"] == ids["minh"]  # mọi trình duyệt trong phòng được báo
    fake_livekit.inside[code] = [ids["minh"], ids["nam"]]

    assert _info(client, minh, code)["can_control"] is True
    assert _info(client, lan, code)["can_control"] is False  # chủ phòng cũ giờ là người thường
    assert _info(client, nam, code)["can_control"] is True  # trưởng nhóm luôn điều khiển được
    assert client.post(f"/api/rooms/{code}/recording/start", headers=auth(lan)).status_code == 403
    assert client.post(f"/api/rooms/{code}/recording/start", headers=auth(minh)).status_code == 200

    # Chủ phòng là người CUỐI CÙNG trong phòng → rời là kết thúc buổi họp
    fake_livekit.inside[code] = [ids["minh"]]
    r = client.post(f"/api/rooms/{code}/leave", headers=auth(minh))
    assert r.json()["room"]["status"] == "ended" and code not in fake_livekit.rooms
    # Có ghi âm → có cuộc họp; người duyệt = chủ phòng LÚC KẾT THÚC (Minh)
    with SessionLocal() as db:
        assert db.get(Meeting, r.json()["meeting_id"]).created_by == ids["minh"]


def test_absent_host_loses_role_after_a_minute(client, fake_livekit):
    """Chủ phòng mất mạng / mất điện: vắng quá 1 phút mới nhượng quyền; vào lại kịp thì vẫn là chủ phòng."""
    nam, lan, ws = _setup(client)
    code = _open(client, nam, ws)["code"]  # Nam vừa là trưởng nhóm vừa là chủ phòng
    nam_id, lan_id = nam["_user"]["id"], lan["_user"]["id"]
    wait = get_settings().ROOM_HOST_ABSENT_SEC

    def tick(shift: int = 0):
        with SessionLocal() as db:
            room = db.query(MeetingRoom).one()
            if shift and room.host_absent_since:
                room.host_absent_since -= timedelta(seconds=shift)
                db.commit()
            room_service.reconcile(db)
            db.refresh(room)
            return room.host_id, room.host_absent_since

    fake_livekit.inside[code] = [nam_id, lan_id]
    assert tick() == (nam_id, None)

    fake_livekit.inside[code] = [lan_id]  # Nam rớt mạng
    host, absent = tick()
    assert host == nam_id and absent is not None  # mới vắng → chưa đổi
    assert tick(shift=wait - 20)[0] == nam_id  # vắng 40 giây → vẫn chưa đổi

    fake_livekit.inside[code] = [lan_id, nam_id]  # Nam vào lại kịp
    assert tick() == (nam_id, None)

    fake_livekit.inside[code] = [lan_id]  # Nam mất điện hẳn
    tick()
    assert tick(shift=wait + 1) == (lan_id, None)  # quá 1 phút → Lan thành chủ phòng
    assert fake_livekit.rooms[code]["host_id"] == lan_id

    # Nam vào lại: không còn là chủ phòng, nhưng vì là TRƯỞNG NHÓM nên vẫn điều khiển được
    fake_livekit.inside[code] = [lan_id, nam_id]
    assert tick() == (lan_id, None)
    info = _info(client, nam, code)
    assert info["is_host"] is False and info["can_control"] is True
    assert _info(client, lan, code)["is_host"] is True


def test_room_that_nobody_managed_to_enter_is_closed_after_a_minute(client, fake_livekit):
    nam, _, ws = _setup(client)
    code = _open(client, nam, ws)["code"]
    s = get_settings()
    with SessionLocal() as db:
        room = db.query(MeetingRoom).one()
        # Vừa tạo, người mở chưa lấy được vé: quá 30 giây chưa đóng vội (có thể mạng chậm)
        room.created_at -= timedelta(seconds=s.ROOM_EMPTY_CLOSE_SEC + 5)
        db.commit()
        room_service.reconcile(db)
        db.refresh(room)
        assert room.status == "open" and room.empty_since is None
        # …quá 1 phút mà vẫn không ai vào thì đóng
        room.created_at -= timedelta(seconds=s.ROOM_UNJOINED_CLOSE_SEC)
        db.commit()
        room_service.reconcile(db)
        db.refresh(room)
        assert room.status == "ended" and room.meeting_id is None
    assert code not in fake_livekit.rooms


# ---------- Ghép bản ghi + lọc tiếng vọng (hàm thuần, không cần CSDL) ----------


def _seg(start, end, text, speaker_id, track_id, rms=None):
    return {"start": start, "end": end, "text": text, "speaker_id": speaker_id, "speaker": f"U{speaker_id}", "track_id": track_id, "rms": rms}


def test_place_segments_shifts_time_and_labels_speaker():
    out = speaker_merge.place_segments(
        [{"start": 1.0, "end": 2.5, "text": " Xin chào. ", "rms": 0.2}, {"start": 3, "end": 4, "text": "  "}], 40.0, 7, "Trần Thị Lan", 3
    )
    assert out == [{"start": 41.0, "end": 42.5, "text": "Xin chào.", "speaker_id": 7, "speaker": "Trần Thị Lan", "track_id": 3, "rms": 0.2}]


def test_echo_is_dropped_and_the_real_speaker_is_kept():
    nam = [_seg(0.0, 4.0, "Lan viết chương hai, nộp trước thứ Sáu tuần này nhé.", 1, 1, rms=0.20)]
    # Lan nghe bằng loa ngoài: mic của Lan thu lại câu của Nam (nhỏ hơn, trễ hơn, cụt đầu)
    lan = [
        _seg(0.6, 4.3, "viết chương hai nộp trước thứ sáu tuần này nhé", 2, 2, rms=0.03),
        _seg(5.0, 6.5, "Dạ vâng em nhận ạ.", 2, 2, rms=0.18),
    ]
    merged, echoes = speaker_merge.merge_tracks([nam, lan])
    assert [(s["speaker_id"], s["text"]) for s in merged] == [
        (1, "Lan viết chương hai, nộp trước thứ Sáu tuần này nhé."),
        (2, "Dạ vâng em nhận ạ."),
    ]
    assert [e["speaker_id"] for e in echoes] == [2]

    # Đảo âm lượng → người to hơn mới là người nói thật
    nam[0]["rms"], lan[0]["rms"] = 0.02, 0.25
    merged, _ = speaker_merge.merge_tracks([nam, lan])
    assert merged[0]["speaker_id"] == 2


def test_echo_filter_handles_mismatched_mic_gain_and_silent_listener():
    """Mic của Lan nhạy hơn mic Nam gấp 10 lần → tiếng vọng ở track Lan có RMS thô TO hơn
    giọng thật của Nam, nhưng so theo RMS TƯƠNG ĐỐI (so với giọng bình thường của chính từng
    mic) thì vẫn nhận đúng Nam là người nói thật."""
    nam = [
        _seg(0.0, 3.0, "Chào mọi người, mình bắt đầu buổi họp tuần nhé.", 1, 1, rms=0.020),
        _seg(5.0, 9.0, "Lan viết chương hai, nộp trước thứ Sáu tuần này nhé.", 1, 1, rms=0.018),
    ]
    lan = [
        _seg(5.4, 9.2, "viết chương hai nộp trước thứ sáu tuần này nhé", 2, 2, rms=0.030),  # vọng: thô 0.030 > 0.018, nhưng chỉ 13% giọng Lan!
        _seg(10.0, 13.0, "Dạ vâng, thứ Sáu em gửi bản nháp cho anh ạ.", 2, 2, rms=0.220),
    ]
    merged, echoes = speaker_merge.merge_tracks([nam, lan])
    assert [e["speaker_id"] for e in echoes] == [2]
    assert [(s["speaker_id"], s["start"]) for s in merged] == [(1, 0.0), (1, 5.0), (2, 10.0)]

    # Trường hợp Lan KHÔNG nói câu nào suốt buổi (chỉ nghe loa ngoài → 100% track Lan là vọng):
    # track Lan không có baseline riêng nên KHÔNG tự đẩy tiếng vọng lên 100%, rơi về RMS thô → vẫn bỏ Lan.
    nam_only = [
        _seg(0.0, 3.0, "Chào mọi người, hôm nay nhóm chốt tiến độ nhé.", 1, 1, rms=0.10),
        _seg(5.0, 8.0, "Tuần này cả nhóm hoàn thành phần thực nghiệm nha.", 1, 1, rms=0.06),
    ]
    lan_silent = [_seg(5.4, 8.2, "tuần này cả nhóm hoàn thành phần thực nghiệm", 2, 2, rms=0.012)]
    merged, echoes = speaker_merge.merge_tracks([nam_only, lan_silent])
    assert [e["speaker_id"] for e in echoes] == [2]
    assert [s["speaker_id"] for s in merged] == [1, 1]

    # Âm lượng tương đương nhau → tiếng vọng (đến trễ hơn do mạng + loa) bị bỏ
    same_a = [_seg(0.0, 3.0, "Mình chốt dùng PostgreSQL cho hệ thống nhé.", 1, 1, rms=0.10)]
    same_b = [_seg(0.4, 3.3, "Mình chốt dùng PostgreSQL cho hệ thống nhé.", 2, 2, rms=0.10)]
    merged, echoes = speaker_merge.merge_tracks([same_a, same_b])
    assert [s["speaker_id"] for s in merged] == [1] and [e["speaker_id"] for e in echoes] == [2]


def test_echo_filter_keeps_real_overlaps():
    a = [_seg(0.0, 1.0, "Dạ vâng ạ.", 1, 1, 0.2), _seg(10.0, 13.0, "Tuần này em viết chương hai.", 1, 1, 0.2)]
    b = [
        _seg(0.2, 1.1, "Dạ vâng ạ.", 2, 2, 0.2),  # hai người cùng "dạ vâng" → câu ngắn, không coi là vọng
        _seg(10.5, 13.5, "Còn anh thì làm phần thực nghiệm.", 2, 2, 0.2),  # nói chen nhưng nội dung khác
        _seg(60.0, 63.0, "Tuần này em viết chương hai.", 2, 2, 0.05),  # giống chữ nhưng cách nhau 50 giây
    ]
    merged, echoes = speaker_merge.merge_tracks([a, b])
    assert len(merged) == 5 and echoes == []
    assert [s["start"] for s in merged] == sorted(s["start"] for s in merged)  # xếp theo thời gian
    # Không có số đo âm lượng → bản ngắn hơn bị coi là bản vọng
    x = [_seg(0, 3, "Mai mình họp lúc chín giờ sáng nhé mọi người.", 1, 1)]
    y = [_seg(0.5, 3, "mình họp lúc chín giờ sáng nhé", 2, 2)]
    assert [s["speaker_id"] for s in speaker_merge.merge_tracks([x, y])[0]] == [1]


def test_replace_track_keeps_other_peoples_lines():
    existing = [_seg(0, 2, "Câu của Nam (đã sửa tay).", 1, 1), _seg(3, 4, "Câu cũ của Lan.", 2, 2), _seg(5, 6, "Nam nói tiếp.", 1, 1)]
    new = [_seg(3, 4, "Câu cũ của Lan.", 2, 2), _seg(7, 9, "Phần đến muộn của Lan.", 2, 2)]
    merged, _ = speaker_merge.replace_track(existing, 2, new)
    assert [s["text"] for s in merged] == ["Câu của Nam (đã sửa tay).", "Câu cũ của Lan.", "Nam nói tiếp.", "Phần đến muộn của Lan."]


# ---------- Dùng tên người nói để giao việc (GĐ4 + nhãn người nói) ----------


class FakeLLM:
    name = "fake-llm"
    max_input_chars = 100_000

    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []
        self.last_usage = {"input_tokens": 1, "output_tokens": 1}

    def generate_json(self, system_prompt, user_prompt, schema):
        self.prompts.append(user_prompt)
        return self.answer


MEMBERS = [MemberInfo(1, "Nguyễn Văn Nam", ["Nam"]), MemberInfo(2, "Trần Thị Lan", []), MemberInfo(3, "Trần Thị Lan", [])]
SPOKEN = [
    {"start": 0, "end": 3, "text": "Ai nhận phần slide thuyết trình?", "speaker": "Nguyễn Văn Nam", "speaker_id": 1},
    {"start": 4, "end": 6, "text": "Dạ phần slide để em làm ạ.", "speaker": "Trần Thị Lan", "speaker_id": 3},
    {"start": 7, "end": 10, "text": "Còn em thì chuẩn bị dữ liệu nhé.", "speaker": "Nguyễn Văn Nam", "speaker_id": 1},
]
ANSWER = {
    "summary": {"topic": "Phân công", "key_points": [], "decisions": [], "open_issues": []},
    "action_items": [
        # Người nói tự nhận → LLM ghi tên người nói ở đầu dòng; lỡ chép cả tên vào câu trích dẫn
        {"task": "Làm slide thuyết trình", "assignees": ["Trần Thị Lan"], "due": "", "priority": "medium",
         "evidence": "Trần Thị Lan: Dạ phần slide để em làm ạ."},
        # Giao cho người khác bằng đại từ, không rõ là ai → vẫn là đại từ
        {"task": "Chuẩn bị dữ liệu", "assignees": ["em"], "due": "", "priority": "medium",
         "evidence": "Còn em thì chuẩn bị dữ liệu nhé."},
    ],
}


def test_speaker_label_assigns_self_claimed_task_to_the_speaker():
    llm = FakeLLM(ANSWER)
    res = extract_meeting(llm, SPOKEN, date(2026, 11, 18), MEMBERS)
    # LLM được đọc bản ghi có tên người nói ở đầu dòng
    assert "Trần Thị Lan: Dạ phần slide để em làm ạ." in llm.prompts[0]

    slide, data = res.items
    # Nhóm có HAI bạn tên "Trần Thị Lan": ghép theo tên sẽ là "ambiguous", nhưng nhãn người nói
    # chỉ đúng tài khoản đã nói câu đó (id 3)
    assert (slide.assignee_id, slide.assignee_match, slide.assignee_score) == (3, "speaker", 100)
    assert slide.evidence_quote == "Dạ phần slide để em làm ạ." and slide.evidence_found and slide.evidence_start == 4.0
    # "em" do Nam nói với người khác → KHÔNG gán cho Nam, để người duyệt chọn
    assert (data.assignee_id, data.assignee_match) == (None, "self")

    # LLM chỉ ghi tên gọi "Lan" (không chép cả họ tên): hai bạn Lan → lẽ ra "ambiguous", nhưng người
    # nói câu đó là Lan (id 3) → vẫn chọn đúng. Còn Nam nói "Nam sẽ…" / LLM ghi "Nam" cũng là tự nhận.
    short = {
        **ANSWER,
        "action_items": [
            {**ANSWER["action_items"][0], "assignees": ["Lan"], "evidence": "Dạ phần slide để em làm ạ."},
            {"task": "Hỏi ai nhận slide", "assignees": ["Nam"], "due": "", "priority": "low", "evidence": "Ai nhận phần slide thuyết trình?"},
            # Nam GIAO việc cho Lan bằng tên → người làm khác người nói → ghép tên bình thường
            {"task": "Chuẩn bị dữ liệu", "assignees": ["Lan"], "due": "", "priority": "medium", "evidence": "Còn em thì chuẩn bị dữ liệu nhé."},
        ],
    }
    a, b, c = extract_meeting(FakeLLM(short), SPOKEN, date(2026, 11, 18), MEMBERS).items
    assert (a.assignee_id, a.assignee_match) == (3, "speaker")
    assert (b.assignee_id, b.assignee_match) == (1, "speaker")
    assert (c.assignee_id, c.assignee_match) == (None, "ambiguous")


def test_without_speaker_labels_behaves_like_phase_4():
    """Thí nghiệm có / không có nhãn người nói: tắt nhãn thì LLM không thấy tên, kết quả như bản ghi thường."""
    llm = FakeLLM(ANSWER)
    res = extract_meeting(llm, SPOKEN, date(2026, 11, 18), MEMBERS, use_speakers=False)
    assert "Trần Thị Lan:" not in llm.prompts[0] and "Dạ phần slide để em làm ạ." in llm.prompts[0]
    assert res.items[0].assignee_match == "ambiguous" and res.items[0].assignee_id is None
