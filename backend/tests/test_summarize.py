"""Test Giai đoạn 4 qua API + worker: bấm tóm tắt → job chạy (LLM giả) → biên bản + đầu việc nháp."""

import pytest

from app.ai.llm import LLMError
from app.models import MeetingStatus
from app.services import meeting_service as svc
from tests.conftest import auth, register

TRANSCRIPT = (
    "Chào mọi người, mình bắt đầu buổi họp tuần nhé.\n"
    "Lan viết chương hai, nộp trước thứ Sáu tuần này nhé.\n"
    "Còn phần anh, anh sẽ chuẩn bị bộ dữ liệu thử nghiệm, xong trước thứ Tư tuần sau.\n"
    "Duy liên hệ thầy hướng dẫn trong ngày mai."
)
LLM_ANSWER = {
    "summary": {
        "topic": "Họp tuần nhóm khóa luận",
        "key_points": ["Phân công viết báo cáo", "Chuẩn bị dữ liệu thử nghiệm"],
        "decisions": ["Lan viết chương hai"],
        "open_issues": [],
    },
    "action_items": [
        {"task": "Viết chương 2", "assignees": ["Lan"], "due": "thứ Sáu tuần này", "priority": "high",
         "evidence": "Lan viết chương hai, nộp trước thứ Sáu tuần này nhé."},
        {"task": "Chuẩn bị bộ dữ liệu thử nghiệm", "assignees": ["anh"], "due": "thứ Tư tuần sau", "priority": "medium",
         "evidence": "Còn phần anh, anh sẽ chuẩn bị bộ dữ liệu thử nghiệm, xong trước thứ Tư tuần sau."},
        {"task": "Liên hệ thầy hướng dẫn", "assignees": ["Duy"], "due": "ngày mai", "priority": "medium",
         "evidence": "Duy liên hệ thầy hướng dẫn trong ngày mai."},
    ],
}


class FakeLLM:
    name = "fake-llm"
    max_input_chars = 100_000

    def __init__(self, answer=None, error: Exception | None = None):
        self.answer = answer or LLM_ANSWER
        self.error = error
        self.prompts: list[str] = []
        self.last_usage = {"input_tokens": 500, "output_tokens": 80}

    def generate_json(self, system_prompt, user_prompt, schema):
        self.prompts.append(user_prompt)
        if self.error:
            raise self.error
        return self.answer


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch):
    """Không đẩy job thật lên Redis: chỉ ghi lại việc nào được đưa vào hàng đợi."""
    queued: list[tuple[str, int]] = []

    def fake_summarize(meeting):
        queued.append(("summarize", meeting.id))
        meeting.status, meeting.progress, meeting.error = MeetingStatus.SUMMARIZING, 0, None

    def fake_transcribe(meeting):
        queued.append(("transcribe", meeting.id))
        meeting.status, meeting.progress, meeting.error = MeetingStatus.QUEUED, 0, None

    monkeypatch.setattr(svc, "enqueue_summarization", fake_summarize)
    monkeypatch.setattr(svc, "enqueue_transcription", fake_transcribe)
    return queued


def _setup(client):
    """Nhóm 2 người: Nam (trưởng nhóm, người tải cuộc họp) và Lan."""
    nam = register(client, "nam@example.com", "Nguyễn Văn Nam")
    lan = register(client, "lan@example.com", "Trần Thị Lan")
    ws = client.post("/api/workspaces", json={"name": "Nhóm KLTN"}, headers=auth(nam)).json()
    client.post(f"/api/workspaces/{ws['id']}/members", json={"email": "lan@example.com"}, headers=auth(nam))
    client.patch(
        f"/api/workspaces/{ws['id']}/members/{lan['_user']['id']}", json={"nicknames": ["Lan", "chị Lan"]}, headers=auth(nam)
    )
    r = client.post(
        f"/api/workspaces/{ws['id']}/meetings",
        data={"title": "Họp tuần 1", "meeting_date": "2026-11-16", "text": TRANSCRIPT},
        headers=auth(nam),
    )
    assert r.status_code == 201, r.text
    return nam, lan, ws, r.json()


def _run_job(monkeypatch, meeting_id, llm):
    from app.workers import jobs

    monkeypatch.setattr(jobs, "get_llm_provider", lambda: llm)
    return jobs.summarize_meeting_job(meeting_id)


def test_summarize_flow(client, monkeypatch, fake_queue):
    nam, lan, ws, m = _setup(client)
    assert m["summary"] is None and m["extracted_tasks"] == []

    r = client.post(f"/api/meetings/{m['id']}/summarize", headers=auth(nam))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "summarizing" and fake_queue == [("summarize", m["id"])]
    # Đang tóm tắt thì không bấm lần nữa, không sửa bản ghi
    assert client.post(f"/api/meetings/{m['id']}/summarize", headers=auth(nam)).status_code == 409
    r = client.put(f"/api/meetings/{m['id']}/transcript", json={"segments": [{"text": "x"}]}, headers=auth(nam))
    assert r.status_code == 409

    llm = FakeLLM()
    assert _run_job(monkeypatch, m["id"], llm) == {"tasks": 3, "chunks": 1, "processing_sec": pytest.approx(0, abs=5)}
    # Prompt chứa ngày họp và thành viên nhóm kèm biệt danh
    assert "Thứ Hai, ngày 16/11/2026" in llm.prompts[0]
    assert "Trần Thị Lan (còn gọi là: Lan, chị Lan)" in llm.prompts[0]

    d = client.get(f"/api/meetings/{m['id']}", headers=auth(lan)).json()  # thành viên khác cũng xem được
    assert d["status"] == "review" and d["progress"] == 100 and d["error"] is None
    s = d["summary"]
    assert s["topic"] == "Họp tuần nhóm khóa luận" and len(s["key_points"]) == 2 and s["decisions"] == ["Lan viết chương hai"]
    assert s["llm_model"] == "fake-llm" and s["chunk_count"] == 1 and s["stale"] is False

    t1, t2, t3 = d["extracted_tasks"]
    # Ghép được tài khoản + tính được ngày
    assert t1["title"] == "Viết chương 2" and t1["assignee"]["email"] == "lan@example.com"
    assert (t1["assignee_match"], t1["due_date"], t1["due_approximate"], t1["priority"]) == ("exact", "2026-11-20", False, "high")
    assert t1["evidence_found"] is True and t1["evidence_segment"] == 1 and t1["status"] == "pending"
    # Người nói tự nhận việc → để trống người làm, chờ duyệt (KHÔNG mặc định gán cho người tạo cuộc họp)
    assert t2["assignee"] is None and (t2["raw_assignee"], t2["assignee_match"]) == ("anh", "self")
    assert t2["due_date"] == "2026-11-25"
    # Người chưa có tài khoản → giữ tên dạng chữ
    assert t3["assignee"] is None and (t3["raw_assignee"], t3["assignee_match"]) == ("Duy", "none")
    assert t3["due_date"] == "2026-11-17"

    # Chưa có thẻ nào bị tạo trên bảng: đây mới là bản nháp (đẩy lên bảng là việc của Giai đoạn 5)
    assert client.get("/api/me/tasks", headers=auth(lan)).json() == []


def test_resummarize_replaces_old_result_and_stale_flag(client, monkeypatch):
    nam, lan, ws, m = _setup(client)
    _run_job(monkeypatch, m["id"], FakeLLM())

    # Sửa bản ghi sau khi tóm tắt → biên bản bị đánh dấu "đã cũ"
    segs = [{"text": "Lan viết chương ba, nộp trước thứ Bảy tuần này nhé."}]
    r = client.put(f"/api/meetings/{m['id']}/transcript", json={"segments": segs}, headers=auth(nam))
    assert r.status_code == 200
    assert r.json()["status"] == "review" and r.json()["summary"]["stale"] is True

    answer = {
        "summary": {"topic": "Bản mới", "key_points": [], "decisions": [], "open_issues": ["Chưa chốt ngày demo"]},
        "action_items": [{"task": "Viết chương 3", "assignees": ["chị Lan"], "due": "thứ Bảy tuần này", "priority": "low",
                          "evidence": "Lan viết chương ba, nộp trước thứ Bảy tuần này nhé."}],
    }
    assert client.post(f"/api/meetings/{m['id']}/summarize", headers=auth(nam)).status_code == 200
    _run_job(monkeypatch, m["id"], FakeLLM(answer))

    d = client.get(f"/api/meetings/{m['id']}", headers=auth(nam)).json()
    assert d["status"] == "review" and d["summary"]["topic"] == "Bản mới" and d["summary"]["stale"] is False
    assert d["summary"]["open_issues"] == ["Chưa chốt ngày demo"]
    assert [(t["title"], t["assignee"]["email"], t["due_date"]) for t in d["extracted_tasks"]] == [
        ("Viết chương 3", "lan@example.com", "2026-11-21")
    ]


def test_llm_failure_keeps_transcript_and_previous_result(client, monkeypatch):
    nam, lan, ws, m = _setup(client)

    # Lần đầu lỗi (hết hạn mức) → quay về "đã có bản ghi", bản ghi còn nguyên, có thông báo lỗi
    res = _run_job(monkeypatch, m["id"], FakeLLM(error=LLMError("Gemini API báo hết hạn mức miễn phí")))
    assert "hết hạn mức" in res["error"]
    d = client.get(f"/api/meetings/{m['id']}", headers=auth(nam)).json()
    assert d["status"] == "transcribed" and "Tóm tắt thất bại" in d["error"] and "hết hạn mức" in d["error"]
    assert d["transcript"]["full_text"] == TRANSCRIPT and d["summary"] is None

    # Bấm lại → thành công, lỗi được xóa
    client.post(f"/api/meetings/{m['id']}/summarize", headers=auth(nam))
    _run_job(monkeypatch, m["id"], FakeLLM())
    d = client.get(f"/api/meetings/{m['id']}", headers=auth(nam)).json()
    assert d["status"] == "review" and d["error"] is None and len(d["extracted_tasks"]) == 3

    # Tóm tắt lại mà lỗi (lỗi bất ngờ, không phải LLMError) → GIỮ kết quả cũ, vẫn ở bước duyệt
    _run_job(monkeypatch, m["id"], FakeLLM(error=RuntimeError("mất mạng")))
    d = client.get(f"/api/meetings/{m['id']}", headers=auth(nam)).json()
    assert d["status"] == "review" and "RuntimeError" in d["error"]
    assert d["summary"]["topic"] == "Họp tuần nhóm khóa luận" and len(d["extracted_tasks"]) == 3


def test_fallback_model_is_shown_while_running_and_on_summary(client, monkeypatch):
    """Mô hình chính quá tải → worker hiện thông báo ngay lúc chuyển, biên bản ghi rõ do mô hình dự phòng viết."""
    from app.core.database import SessionLocal
    from app.models import Meeting

    nam, lan, ws, m = _setup(client)
    seen_notes: list[str | None] = []

    class FallbackLLM(FakeLLM):
        name = "gemini/flash-lite"
        fallback_from = None

        def begin_job(self, on_fallback=None):
            self.on_fallback = on_fallback

        def generate_json(self, system_prompt, user_prompt, schema):
            self.fallback_from = "flash"
            self.on_fallback("Mô hình flash đang quá tải (503), hệ thống đã tự chuyển sang mô hình dự phòng flash-lite…")
            with SessionLocal() as db:  # lúc này giao diện đọc được thông báo
                seen_notes.append(db.get(Meeting, m["id"]).status_note)
            return super().generate_json(system_prompt, user_prompt, schema)

    _run_job(monkeypatch, m["id"], FallbackLLM())
    assert seen_notes and "dự phòng flash-lite" in seen_notes[0]

    d = client.get(f"/api/meetings/{m['id']}", headers=auth(nam)).json()
    assert d["status"] == "review" and d["status_note"] is None  # xong thì xóa thông báo tạm
    assert d["summary"]["llm_model"] == "gemini/flash-lite" and d["summary"]["fallback_from"] == "flash"

    # Tóm tắt lại bằng mô hình chính bình thường → hết nhãn "dự phòng"
    client.post(f"/api/meetings/{m['id']}/summarize", headers=auth(nam))
    _run_job(monkeypatch, m["id"], FakeLLM())
    d = client.get(f"/api/meetings/{m['id']}", headers=auth(nam)).json()
    assert d["summary"]["fallback_from"] is None and d["summary"]["llm_model"] == "fake-llm"


def test_summarize_requires_transcript_and_membership(client, fake_queue):
    nam, lan, ws, m = _setup(client)
    stranger = register(client, "s@example.com")
    assert client.post(f"/api/meetings/{m['id']}/summarize", headers=auth(stranger)).status_code == 404

    # Ghi âm vừa tải lên, chưa có bản ghi → chưa tóm tắt được
    r = client.post(
        f"/api/workspaces/{ws['id']}/meetings",
        data={"title": "Ghi âm", "meeting_date": "2026-11-16"},
        files={"file": ("hop.mp3", b"ID3" + b"x" * 300, "audio/mpeg")},
        headers=auth(nam),
    )
    assert r.status_code == 201 and r.json()["status"] == "queued"
    assert client.post(f"/api/meetings/{r.json()['id']}/summarize", headers=auth(nam)).status_code == 409
    assert ("summarize", r.json()["id"]) not in fake_queue


def test_retranscribe_clears_old_summary(client, monkeypatch, fake_queue):
    """Nhận dạng lại giọng nói → bản ghi sẽ khác → biên bản và đầu việc nháp cũ bị xóa."""
    from app.ai.stt.base import Segment, TranscriptResult
    from app.workers import jobs

    class FakeSTT:
        name = "fake-whisper"

        def transcribe(self, audio_path, language="vi", on_progress=None, initial_prompt=None):
            segs = [Segment(0.0, 3.0, "Lan viết chương hai, nộp trước thứ Sáu tuần này nhé.")]
            return TranscriptResult(text=segs[0].text, segments=segs, duration_sec=3.0, processing_sec=0.5, model=self.name)

    nam, lan, ws, _ = _setup(client)
    r = client.post(
        f"/api/workspaces/{ws['id']}/meetings",
        data={"title": "Ghi âm", "meeting_date": "2026-11-16"},
        files={"file": ("hop.mp3", b"ID3" + b"x" * 300, "audio/mpeg")},
        headers=auth(nam),
    )
    mid = r.json()["id"]
    monkeypatch.setattr(jobs, "get_stt_provider", lambda: FakeSTT())
    jobs.process_meeting_job(mid)
    _run_job(monkeypatch, mid, FakeLLM())
    d = client.get(f"/api/meetings/{mid}", headers=auth(nam)).json()
    assert d["status"] == "review" and len(d["extracted_tasks"]) == 3
    assert d["extracted_tasks"][0]["evidence_start"] == 0.0  # có mốc thời gian → bấm vào nghe lại được

    r = client.post(f"/api/meetings/{mid}/retry", headers=auth(nam))
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert r.json()["summary"] is None and r.json()["extracted_tasks"] == []


def test_summarize_job_skips_deleted_meeting(client, monkeypatch):
    from app.workers import jobs

    assert jobs.summarize_meeting_job(999999) == {"skipped": True}

    nam, lan, ws, m = _setup(client)
    _run_job(monkeypatch, m["id"], FakeLLM())
    # Xóa cuộc họp → biên bản và đầu việc nháp bị xóa theo (ON DELETE CASCADE)
    assert client.delete(f"/api/meetings/{m['id']}", headers=auth(nam)).status_code == 204
    assert client.get(f"/api/meetings/{m['id']}", headers=auth(nam)).status_code == 404
