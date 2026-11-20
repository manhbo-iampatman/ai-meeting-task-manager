"""Test phân hệ cuộc họp (Giai đoạn 3). Worker dùng bộ STT GIẢ → không cần GPU, chạy nhanh."""

import pytest

from app.ai.stt.base import Segment, TranscriptResult
from app.models import MeetingStatus
from app.services import meeting_service as svc
from tests.conftest import auth, register


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch):
    """Không đẩy job thật lên Redis: chỉ ghi lại id cuộc họp được đưa vào hàng đợi."""
    queued: list[int] = []

    def fake_enqueue(meeting):
        queued.append(meeting.id)
        meeting.job_id = f"fake-{meeting.id}"
        meeting.status = MeetingStatus.QUEUED
        meeting.progress = 0
        meeting.error = None

    monkeypatch.setattr(svc, "enqueue_transcription", fake_enqueue)
    return queued


class FakeSTT:
    name = "fake-whisper"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.prompt: str | None = None

    def transcribe(self, audio_path, language="vi", on_progress=None, initial_prompt=None):
        self.prompt = initial_prompt
        if self.fail:
            raise RuntimeError("CUDA out of memory")
        if on_progress:
            on_progress(0.5)
        segs = [Segment(0.0, 2.5, "Chào mọi người."), Segment(3.0, 6.0, "Nam làm phần cơ sở dữ liệu.")]
        return TranscriptResult(
            text=" ".join(s.text for s in segs), segments=segs, language="vi",
            duration_sec=6.0, processing_sec=1.2, model=self.name,
        )


def _setup(client):
    owner = register(client, "owner@example.com", "Nguyễn Văn Nam")
    ws = client.post("/api/workspaces", json={"name": "Nhóm KLTN"}, headers=auth(owner)).json()
    uid = owner["_user"]["id"]
    client.patch(f"/api/workspaces/{ws['id']}/members/{uid}", json={"nicknames": ["Nam", "anh Nam"]}, headers=auth(owner))
    return owner, ws


def _upload_audio(client, owner, ws, content=b"ID3fake-mp3-bytes" * 100, name="hop-tuan.mp3"):
    return client.post(
        f"/api/workspaces/{ws['id']}/meetings",
        data={"title": "Họp tuần 1", "meeting_date": "2026-11-16"},
        files={"file": (name, content, "audio/mpeg")},
        headers=auth(owner),
    )


def test_create_from_pasted_text(client):
    owner, ws = _setup(client)
    r = client.post(
        f"/api/workspaces/{ws['id']}/meetings",
        data={"title": "Họp nhanh", "meeting_date": "2026-11-16", "text": "Dòng 1\n\n  Dòng 2  \n"},
        headers=auth(owner),
    )
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["source_type"] == "text" and m["status"] == "transcribed"
    assert [s["text"] for s in m["transcript"]["segments"]] == ["Dòng 1", "Dòng 2"]
    assert m["has_audio"] is False


def test_create_from_txt_file(client):
    owner, ws = _setup(client)
    r = client.post(
        f"/api/workspaces/{ws['id']}/meetings",
        data={"title": "Biên bản", "meeting_date": "2026-11-16"},
        files={"file": ("bien-ban.txt", "﻿Lan làm slide.\nMinh sửa lỗi.".encode(), "text/plain")},
        headers=auth(owner),
    )
    assert r.status_code == 201, r.text
    assert r.json()["transcript"]["full_text"] == "Lan làm slide.\nMinh sửa lỗi."


def test_validation(client):
    owner, ws = _setup(client)
    url = f"/api/workspaces/{ws['id']}/meetings"
    base = {"title": "X", "meeting_date": "2026-11-16"}
    assert client.post(url, data=base, headers=auth(owner)).status_code == 400  # không có gì
    r = client.post(url, data=base, files={"file": ("virus.exe", b"MZ", "application/octet-stream")}, headers=auth(owner))
    assert r.status_code == 400
    r = client.post(url, data={**base, "text": "abc"}, files={"file": ("a.mp3", b"x", "audio/mpeg")}, headers=auth(owner))
    assert r.status_code == 400  # vừa file vừa text
    stranger = register(client, "s@example.com")
    assert client.post(url, data={**base, "text": "abc"}, headers=auth(stranger)).status_code == 404


def test_upload_audio_is_queued_and_playable(client, fake_queue):
    owner, ws = _setup(client)
    content = bytes(range(256)) * 40
    r = _upload_audio(client, owner, ws, content=content)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["status"] == "queued" and m["has_audio"] and m["audio_size"] == len(content)
    assert fake_queue == [m["id"]]

    token = owner["Authorization"].split()[1]
    full = client.get(f"/api/meetings/{m['id']}/audio?token={token}")
    assert full.status_code == 200 and full.content == content
    # Range request → tua được tới giữa file
    part = client.get(f"/api/meetings/{m['id']}/audio?token={token}", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == content[100:200]

    stranger = register(client, "s@example.com")
    t2 = stranger["Authorization"].split()[1]
    assert client.get(f"/api/meetings/{m['id']}/audio?token={t2}").status_code == 404
    assert client.get(f"/api/meetings/{m['id']}", headers=auth(stranger)).status_code == 404

    lst = client.get(f"/api/workspaces/{ws['id']}/meetings", headers=auth(owner)).json()
    assert [x["title"] for x in lst] == ["Họp tuần 1"]


def test_audio_served_as_audio_even_if_upload_claims_html(client):
    """Lỗ hổng XSS: tải lên "x.mp3" nhưng khai loại file là trang web có mã độc. Khi phát lại,
    server phải trả loại âm thanh (theo đuôi file) + "nosniff", không bao giờ trả text/html."""
    from app.core.database import SessionLocal
    from app.models import Meeting

    owner, ws = _setup(client)
    evil = b"<html><script>alert(localStorage.getItem('auth'))</script></html>"
    r = client.post(
        f"/api/workspaces/{ws['id']}/meetings",
        data={"title": "Họp", "meeting_date": "2026-11-16"},
        files={"file": ("x.mp3", evil, "text/html")},
        headers=auth(owner),
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    token = owner["Authorization"].split()[1]

    def fetch():
        res = client.get(f"/api/meetings/{mid}/audio?token={token}")
        assert res.status_code == 200
        return res

    res = fetch()
    assert res.headers["content-type"] == "audio/mpeg"
    assert res.headers["x-content-type-options"] == "nosniff"
    with SessionLocal() as db:
        m = db.get(Meeting, mid)
        assert m.audio_mime == "audio/mpeg"  # không lưu loại file do trình duyệt khai báo
        # Cuộc họp cũ (tải lên trước bản sửa) có thể đã lưu loại file giả trong CSDL
        m.audio_mime = "text/html"
        db.commit()
    assert fetch().headers["content-type"] == "audio/mpeg"


def test_worker_job_success_with_member_names_prompt(client, monkeypatch):
    from app.workers import jobs

    owner, ws = _setup(client)
    m = _upload_audio(client, owner, ws).json()
    fake = FakeSTT()
    monkeypatch.setattr(jobs, "get_stt_provider", lambda: fake)

    res = jobs.process_meeting_job(m["id"])
    assert res["segments"] == 2
    # Tên + biệt danh thành viên được đưa vào gợi ý cho Whisper
    assert "Nguyễn Văn Nam (Nam, anh Nam)" in fake.prompt

    d = client.get(f"/api/meetings/{m['id']}", headers=auth(owner)).json()
    assert d["status"] == "transcribed" and d["progress"] == 100
    assert d["transcript"]["segments"][1] == {"start": 3.0, "end": 6.0, "text": "Nam làm phần cơ sở dữ liệu."}
    assert d["transcript"]["stt_model"] == "fake-whisper" and d["duration_sec"] == 6.0


def test_worker_job_failure_then_retry(client, monkeypatch, fake_queue):
    from app.workers import jobs

    owner, ws = _setup(client)
    m = _upload_audio(client, owner, ws).json()
    monkeypatch.setattr(jobs, "get_stt_provider", lambda: FakeSTT(fail=True))
    jobs.process_meeting_job(m["id"])

    d = client.get(f"/api/meetings/{m['id']}", headers=auth(owner)).json()
    assert d["status"] == "failed" and "CUDA out of memory" in d["error"]

    r = client.post(f"/api/meetings/{m['id']}/retry", headers=auth(owner))
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["error"] is None
    assert fake_queue == [m["id"], m["id"]]
    # Đang trong hàng đợi thì không cho thử lại lần nữa
    assert client.post(f"/api/meetings/{m['id']}/retry", headers=auth(owner)).status_code == 409


def test_edit_transcript_and_delete(client, monkeypatch):
    from app.workers import jobs

    owner, ws = _setup(client)
    m = _upload_audio(client, owner, ws).json()
    # Chưa có bản ghi → chưa sửa được
    r = client.put(f"/api/meetings/{m['id']}/transcript", json={"segments": [{"text": "x"}]}, headers=auth(owner))
    assert r.status_code == 409

    monkeypatch.setattr(jobs, "get_stt_provider", lambda: FakeSTT())
    jobs.process_meeting_job(m["id"])

    segs = [
        {"start": 0.0, "end": 2.5, "text": "Chào mọi người."},
        {"start": 3.0, "end": 6.0, "text": " Anh Nam làm phần cơ sở dữ liệu, hạn thứ Sáu. "},
        {"start": 6.0, "end": 7.0, "text": "   "},  # đoạn rỗng bị bỏ
    ]
    r = client.put(f"/api/meetings/{m['id']}/transcript", json={"segments": segs}, headers=auth(owner))
    assert r.status_code == 200
    tr = r.json()["transcript"]
    assert tr["edited"] is True and len(tr["segments"]) == 2
    assert tr["full_text"] == "Chào mọi người. Anh Nam làm phần cơ sở dữ liệu, hạn thứ Sáu."

    path = svc.upload_root() / "meetings" / f"{m['id']}.mp3"
    assert path.exists()
    assert client.delete(f"/api/meetings/{m['id']}", headers=auth(owner)).status_code == 204
    assert not path.exists()
    assert client.get(f"/api/meetings/{m['id']}", headers=auth(owner)).status_code == 404


def test_job_skips_deleted_meeting():
    from app.workers import jobs

    assert jobs.process_meeting_job(999999) == {"skipped": True}


def test_no_speech_detected_is_reported_as_failed(client, monkeypatch):
    """File nhạc / im lặng → Whisper không ra câu nào → báo lỗi rõ ràng, không "có bản ghi" rỗng."""
    from app.workers import jobs

    class SilentSTT(FakeSTT):
        def transcribe(self, audio_path, language="vi", on_progress=None, initial_prompt=None):
            return TranscriptResult(text="", segments=[], language="vi", duration_sec=241.0, processing_sec=2.3, model=self.name)

    owner, ws = _setup(client)
    m = _upload_audio(client, owner, ws).json()
    monkeypatch.setattr(jobs, "get_stt_provider", lambda: SilentSTT())
    jobs.process_meeting_job(m["id"])

    d = client.get(f"/api/meetings/{m['id']}", headers=auth(owner)).json()
    assert d["status"] == "failed"
    assert "Không nhận ra lời nói" in d["error"]
    assert d["transcript"] is None


def _make_webm(path, seconds=2.0, sr=48000):
    """Tạo file webm/opus ngắn (tiếng bíp 440Hz) giống định dạng trình duyệt ghi ra."""
    import av
    import numpy as np

    with av.open(str(path), "w", format="webm") as out:
        st = out.add_stream("libopus", rate=sr)
        st.layout = "mono"
        t = np.arange(int(sr * seconds)) / sr
        pcm = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        for i in range(0, len(pcm), 960):
            frame = av.AudioFrame.from_ndarray(pcm[i : i + 960].reshape(1, -1), format="s16", layout="mono")
            frame.rate = sr
            for p in st.encode(frame):
                out.mux(p)
        for p in st.encode(None):
            out.mux(p)


def test_fix_webm_duration(tmp_path):
    import av

    f = tmp_path / "ghi-am.webm"
    _make_webm(f)
    assert svc.fix_webm_duration(f) is True
    with av.open(str(f)) as c:
        assert abs(c.duration / 1_000_000 - 2.0) < 0.2  # thời lượng được ghi vào file
    assert svc.fix_webm_duration(tmp_path / "khac.mp3") is False  # chỉ xử lý .webm


def test_recorded_source_type(client, fake_queue):
    owner, ws = _setup(client)
    r = client.post(
        f"/api/workspaces/{ws['id']}/meetings",
        data={"title": "Ghi trực tiếp", "meeting_date": "2026-11-16", "recorded": "true"},
        files={"file": ("ghi-am.webm", b"\x1aE\xdf\xa3" + b"x" * 500, "audio/webm")},
        headers=auth(owner),
    )
    assert r.status_code == 201, r.text
    assert r.json()["source_type"] == "recording" and r.json()["status"] == "queued"
