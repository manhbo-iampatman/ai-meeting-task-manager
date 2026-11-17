"""Test phần LLM Giai đoạn 4 bằng mô hình GIẢ → không tốn hạn mức API, không cần mạng, chạy trong vài giây."""

import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from app.ai.extraction import extract_meeting, find_evidence
from app.ai.llm.base import LLMError, parse_json_text
from app.ai.llm.chunking import chunk_lines
from app.ai.llm.gemini_provider import GeminiProvider
from app.ai.llm.ollama_provider import OllamaProvider
from app.ai.llm.prompts import EXTRACTION_SCHEMA, SUMMARY_SCHEMA, build_user_prompt
from app.ai.postprocess.name_matching import MemberInfo

MEETING_DATE = date(2026, 11, 16)
MEMBERS = [
    MemberInfo(1, "Nguyễn Văn Nam", ["Nam", "anh Nam"]),
    MemberInfo(2, "Trần Thị Lan", ["Lan"]),
    MemberInfo(3, "Lê Quang Minh", []),
]
LINES = [
    "Chào mọi người, mình bắt đầu buổi họp tuần nhé.",
    "Lan viết chương hai, nộp trước thứ Sáu tuần này nhé.",
    "Vâng, thứ Sáu em gửi bản nháp cho anh.",
    "Còn phần anh, anh sẽ chuẩn bị bộ dữ liệu thử nghiệm, xong trước thứ Tư tuần sau.",
    "Lan và Minh làm slide báo cáo, cuối tuần này xong nhé.",
]
SEGMENTS = [{"start": i * 5.0, "end": i * 5.0 + 4, "text": t} for i, t in enumerate(LINES)]


def summary(topic="Họp tuần nhóm khóa luận"):
    return {"topic": topic, "key_points": ["Phân công viết báo cáo"], "decisions": [], "open_issues": []}


def item(task, assignees, due="", evidence="", priority="medium"):
    return {"task": task, "assignees": assignees, "due": due, "priority": priority, "evidence": evidence}


class FakeLLM:
    """LLM giả: trả về lần lượt các câu trả lời đã soạn sẵn, ghi lại prompt đã nhận."""

    name = "fake-llm"

    def __init__(self, responses, max_input_chars=100_000):
        self.responses = list(responses)
        self.max_input_chars = max_input_chars
        self.calls: list[tuple[str, str, dict]] = []
        self.last_usage = {"input_tokens": 100, "output_tokens": 20}

    def generate_json(self, system_prompt, user_prompt, schema):
        self.calls.append((system_prompt, user_prompt, schema))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# ---------------- Pipeline trích xuất ----------------


def test_extract_meeting_end_to_end():
    llm = FakeLLM([
        {
            "summary": summary(),
            "action_items": [
                item("Viết chương 2", ["Lan"], "thứ Sáu tuần này", LINES[1], "high"),
                item("Chuẩn bị bộ dữ liệu thử nghiệm", ["anh"], "thứ Tư tuần sau", LINES[3]),
                item("Làm slide báo cáo", ["Lan", "Minh"], "cuối tuần này", LINES[4]),
                item("Mua bánh sinh nhật", ["Duy"], "", "Duy mua bánh sinh nhật cho cả nhóm nhé."),  # câu bịa
            ],
        }
    ])
    progress: list[float] = []
    r = extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS, on_progress=progress.append)

    assert r.llm_model == "fake-llm" and r.chunk_count == 1 and progress == [1.0]
    assert r.summary["topic"] == "Họp tuần nhóm khóa luận"
    assert (r.input_tokens, r.output_tokens) == (100, 20)
    by_key = {(i.title, i.raw_assignee): i for i in r.items}
    assert len(r.items) == 5  # việc của "Lan và Minh" được tách thành 2

    lan = by_key[("Viết chương 2", "Lan")]
    assert lan.assignee_id == 2 and lan.assignee_match == "exact"
    assert lan.due_date == date(2026, 11, 20) and lan.due_approximate is False and lan.due_text == "thứ Sáu tuần này"
    assert lan.priority == "high"
    assert lan.evidence_found and lan.evidence_segment == 1 and lan.evidence_start == 5.0

    # Người nói tự nhận việc → KHÔNG đoán, để trống cho người dùng chọn khi duyệt
    self_task = by_key[("Chuẩn bị bộ dữ liệu thử nghiệm", "anh")]
    assert self_task.assignee_id is None and self_task.assignee_match == "self"
    assert self_task.due_date == date(2026, 11, 25)

    # Một việc giao 2 người → mỗi người một đầu việc, hạn mơ hồ được đánh dấu "ước lượng"
    for name, uid in (("Lan", 2), ("Minh", 3)):
        t = by_key[("Làm slide báo cáo", name)]
        assert t.assignee_id == uid
        assert t.due_date == date(2026, 11, 22) and t.due_approximate is True

    # Người không có trong nhóm → giữ tên dạng chữ; câu trích dẫn không có trong bản ghi → cảnh báo
    duy = by_key[("Mua bánh sinh nhật", "Duy")]
    assert duy.assignee_id is None and duy.assignee_match == "none"
    assert duy.evidence_found is False and duy.evidence_start is None
    assert duy.due_date is None and duy.due_text is None

    # Prompt có ngày họp (kèm thứ), danh sách thành viên + biệt danh, và bản ghi
    system, user, schema = llm.calls[0]
    assert "Thứ Hai, ngày 16/11/2026" in user
    assert "Nguyễn Văn Nam (còn gọi là: Nam, anh Nam)" in user
    assert LINES[1] in user and schema is EXTRACTION_SCHEMA
    assert "KHÔNG được đoán tên" in system


def test_extract_without_members_in_prompt():
    """Thí nghiệm "không đưa danh sách thành viên vào prompt": tên vẫn được ghép ở bước hậu xử lý."""
    llm = FakeLLM([{"summary": summary(), "action_items": [item("Viết chương 2", ["Lan"], "", LINES[1])]}])
    r = extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS, include_members=False)
    assert "Thành viên nhóm" not in llm.calls[0][1]
    assert r.items[0].assignee_id == 2


def test_duplicate_tasks_are_merged():
    """Cuối họp nhắc lại "chốt lại: Lan viết chương hai" → không tạo 2 đầu việc."""
    llm = FakeLLM([
        {
            "summary": summary(),
            "action_items": [
                item("Viết chương 2", ["Lan"], "", LINES[1]),
                item("Viết chương 2", ["Lan"], "thứ Sáu tuần này", LINES[1]),  # bản trùng có hạn chót
                item("Viết chương 2", ["Minh"], "", LINES[1]),  # cùng việc nhưng người khác → giữ
            ],
        }
    ])
    r = extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS)
    assert [(i.raw_assignee, i.due_date) for i in r.items] == [("Lan", date(2026, 11, 20)), ("Minh", None)]


def test_same_task_rules():
    from app.ai.extraction import same_task

    # Bản nhắc lại ngắn gọn ở cuối họp (lỗi gặp thật khi chạy Gemini trên bản ghi chia đoạn)
    assert same_task("Viết chương 2, phần cơ sở lý thuyết về nhận dạng giọng nói", "Viết chương 2")
    assert same_task("Hoàn thành trình phát âm thanh và sửa lỗi hiển thị trên điện thoại", "Làm trình phát âm thanh")
    # Chữ giống nhau nhưng khác SỐ → hai việc khác nhau
    assert not same_task("Viết chương 2", "Viết chương 3")
    assert not same_task("Chuẩn bị 10 đoạn ghi âm", "Chuẩn bị 20 đoạn ghi âm")
    # Hai việc khác nhau của cùng một người
    assert not same_task("Viết chương 2", "Gửi email hẹn lịch với thầy hướng dẫn")
    assert not same_task("Sửa lỗi hiển thị trên điện thoại", "Sửa lỗi đăng nhập trên máy tính")


def test_recap_duplicate_keeps_detailed_version():
    llm = FakeLLM([
        {
            "summary": summary(),
            "action_items": [
                item("Viết chương 2", ["Lan"], "", "Lan viết chương hai"),  # câu nhắc lại, không có hạn
                item("Viết chương 2, phần cơ sở lý thuyết", ["Lan"], "thứ Sáu tuần này", LINES[1], "high"),
                item("Viết chương 3", ["Lan"], "", LINES[1]),  # việc khác (khác số) → giữ
            ],
        }
    ])
    r = extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS)
    assert [(i.title, i.due_date, i.priority) for i in r.items] == [
        ("Viết chương 2, phần cơ sở lý thuyết", date(2026, 11, 20), "high"),
        ("Viết chương 3", None, "medium"),
    ]
    assert r.items[0].evidence_segment == 1


def test_long_transcript_is_chunked_then_reduced():
    """Bản ghi dài hơn sức đọc của mô hình → chia đoạn (map), rồi gộp biên bản (reduce)."""
    llm = FakeLLM(
        [
            {"summary": summary("Phần 1"), "action_items": [item("Viết chương 2", ["Lan"], "thứ Sáu tuần này", LINES[1])]},
            {"summary": summary("Phần 2"), "action_items": [item("Viết chương 2", ["Lan"], "", LINES[1])]},  # trùng do gối đầu
            {"summary": summary("Phần 3"), "action_items": [item("Làm slide báo cáo", ["Minh"], "", LINES[4])]},
            summary("Cả cuộc họp"),  # câu trả lời của bước reduce
        ],
        max_input_chars=130,
    )
    progress: list[float] = []
    r = extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS, on_progress=progress.append)

    assert r.chunk_count == 3 and len(llm.calls) == 4
    assert r.summary["topic"] == "Cả cuộc họp"
    assert [(i.title, i.raw_assignee) for i in r.items] == [("Viết chương 2", "Lan"), ("Làm slide báo cáo", "Minh")]
    assert "PHẦN 2/3" in llm.calls[1][1]
    assert llm.calls[3][2] is SUMMARY_SCHEMA and "Phần 1" in llm.calls[3][1]  # reduce nhận các tóm tắt từng phần
    assert progress[-1] == 1.0 and progress == sorted(progress)
    assert r.input_tokens == 400  # cộng dồn cả 4 lần gọi


def test_bad_llm_output_is_retried_then_reported():
    ok = {"summary": summary(), "action_items": [item("Viết chương 2", ["Lan"])]}
    llm = FakeLLM([{"summary": summary(), "action_items": "không phải mảng"}, ok])
    assert len(extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS).items) == 1  # lần 2 đúng → dùng

    llm = FakeLLM([{"action_items": 5}, {"action_items": 5}])
    with pytest.raises(LLMError, match="sai cấu trúc"):
        extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS)


def test_llm_output_is_tolerant_to_small_deviations():
    """Mô hình nhỏ hay trả thiếu trường / sai kiểu → sửa nhẹ nhàng thay vì báo lỗi."""
    llm = FakeLLM([
        {
            "summary": {"topic": None, "key_points": "Một ý duy nhất"},
            "action_items": [
                {"task": "  Viết chương 2 ", "assignees": "Lan", "priority": "URGENT", "due": None},
                {"task": "", "assignees": ["Minh"]},  # không có nội dung → bỏ
            ],
        }
    ])
    r = extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS)
    assert r.summary == {"topic": "", "key_points": ["Một ý duy nhất"], "decisions": [], "open_issues": []}
    assert len(r.items) == 1
    assert (r.items[0].title, r.items[0].assignee_id, r.items[0].priority) == ("Viết chương 2", 2, "medium")


def test_empty_transcript_is_rejected():
    with pytest.raises(LLMError, match="trống"):
        extract_meeting(FakeLLM([]), [{"text": "   "}], MEETING_DATE, MEMBERS)


def test_find_evidence():
    assert find_evidence(LINES[1], SEGMENTS) == (1, 100)
    # Không dấu / khác hoa thường / chỉ trích một phần câu vẫn tìm ra
    i, score = find_evidence("lan viet chuong hai, nop truoc thu sau tuan nay", SEGMENTS)
    assert i == 1 and score >= 85
    # Câu bịa → điểm thấp
    assert find_evidence("Duy mua bánh sinh nhật cho cả nhóm nhé.", SEGMENTS)[1] < 85
    # Trích dẫn quá ngắn không được "khớp" bừa vào một câu dài
    assert find_evidence("nhé", SEGMENTS)[1] < 85
    # Whisper cắt 1 câu thành 2 dòng → vẫn tìm ra khi ghép 2 dòng liền nhau
    split = [{"start": 0.0, "text": "Lan viết chương hai,"}, {"start": 2.0, "text": "nộp trước thứ Sáu tuần này nhé."}]
    assert find_evidence(LINES[1], split) == (0, 100)


# ---------------- Chia đoạn ----------------


def test_chunk_lines():
    lines = [f"Câu số {i} trong cuộc họp." for i in range(10)]  # mỗi câu 25 ký tự
    chunks = chunk_lines(lines, max_chars=80, overlap=1)
    assert len(chunks) > 1
    assert all(sum(len(x) + 1 for x in c) <= 80 for c in chunks)
    # Không mất câu nào, giữ đúng thứ tự
    flat = [x for i, c in enumerate(chunks) for x in (c if i == 0 else c[1:])]
    assert flat == lines
    # Hai đoạn liền nhau gối lên nhau 1 câu
    assert all(chunks[i][-1] == chunks[i + 1][0] for i in range(len(chunks) - 1))

    assert chunk_lines(lines, max_chars=10_000) == [lines]  # ngắn → không chia
    assert chunk_lines(["a" * 500, "b"], max_chars=100, overlap=2) == [["a" * 500], ["b"]]  # câu quá dài vẫn giữ nguyên


def test_user_prompt_marks_transcript_as_data():
    p = build_user_prompt(MEETING_DATE, [("Trần Thị Lan", [])], "Dòng 1\nDòng 2", part=(2, 3))
    assert "- Trần Thị Lan" in p and "PHẦN 2/3" in p
    assert p.endswith("<<<\nDòng 1\nDòng 2\n>>>")


# ---------------- Đọc JSON ----------------


def test_parse_json_text():
    assert parse_json_text('{"a": 1}') == {"a": 1}
    assert parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}  # mô hình nhỏ hay bọc trong ```
    for bad in ("", None, "xin lỗi tôi không làm được", "[1, 2]"):
        with pytest.raises(LLMError):
            parse_json_text(bad)


# ---------------- Gemini (client giả) ----------------


class FakeGeminiClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.requests.append({"model": model, "contents": contents, "config": config})
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(text=out, usage_metadata=SimpleNamespace(prompt_token_count=321, candidates_token_count=45))


def _api_error(code):
    from google.genai import errors

    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, {"error": {"code": code, "message": "lỗi giả lập", "status": "X"}})


def test_gemini_structured_output_request():
    client = FakeGeminiClient(['{"summary": {}, "action_items": []}'])
    llm = GeminiProvider(api_key="", model="gemini-test", client=client)
    assert llm.generate_json("HỆ THỐNG", "NGƯỜI DÙNG", EXTRACTION_SCHEMA) == {"summary": {}, "action_items": []}
    req = client.requests[0]
    assert req["model"] == "gemini-test" and req["contents"] == "NGƯỜI DÙNG"
    cfg = req["config"]
    assert cfg.system_instruction == "HỆ THỐNG"
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema == EXTRACTION_SCHEMA
    assert llm.name == "gemini/gemini-test" and llm.last_usage == {"input_tokens": 321, "output_tokens": 45}


def test_gemini_retries_temporary_errors():
    client = FakeGeminiClient([_api_error(503), _api_error(429), '{"ok": true}'])
    llm = GeminiProvider(api_key="", model="m", client=client, retry_wait=0)
    assert llm.generate_json("s", "u", {}) == {"ok": True}
    assert len(client.requests) == 3  # 2 lần lỗi tạm thời + 1 lần thành công


def test_gemini_reports_friendly_errors():
    llm = GeminiProvider(api_key="", model="m", client=FakeGeminiClient([_api_error(429)] * 3), retry_wait=0)
    with pytest.raises(LLMError, match="hết hạn mức"):
        llm.generate_json("s", "u", {})

    client = FakeGeminiClient([_api_error(403)])
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiProvider(api_key="", model="m", client=client, retry_wait=0).generate_json("s", "u", {})
    assert len(client.requests) == 1  # sai key thì thử lại cũng vô ích → không thử lại

    with pytest.raises(LLMError, match="Chưa cấu hình GEMINI_API_KEY"):
        GeminiProvider(api_key="", model="m")


# ---------------- Gemini: mô hình dự phòng khi mô hình chính quá tải ----------------


class FakeReadTimeout(Exception):
    """Giống httpx.ReadTimeout: thư viện google-genai ném ra khi hết thời gian chờ ở phía máy mình."""


OK_JSON = '{"ok": true}'


def _gemini_with_fallback(outcomes):
    client = FakeGeminiClient(outcomes)
    llm = GeminiProvider(api_key="", model="flash", fallback_model="flash-lite", client=client, retry_wait=0)
    return llm, client


@pytest.mark.parametrize("failure", [_api_error(503), _api_error(504), _api_error(429), FakeReadTimeout("read timed out")])
def test_gemini_switches_to_fallback_when_main_model_is_overloaded(failure):
    llm, client = _gemini_with_fallback([failure, OK_JSON, OK_JSON])
    notices: list[str] = []
    llm.begin_job(notices.append)
    assert llm.name == "gemini/flash" and llm.fallback_from is None

    assert llm.generate_json("s", "u", {}) == {"ok": True}
    # Không thử lại mô hình đang quá tải: chuyển NGAY sang mô hình dự phòng
    assert [r["model"] for r in client.requests] == ["flash", "flash-lite"]
    assert llm.name == "gemini/flash-lite" and llm.fallback_from == "flash"
    assert len(notices) == 1 and "flash-lite" in notices[0] and "dự phòng" in notices[0]

    # Các lần gọi tiếp theo trong CÙNG lần tóm tắt (bản ghi dài, nhiều đoạn) dùng luôn mô hình dự phòng
    llm.generate_json("s", "u", {})
    assert client.requests[-1]["model"] == "flash-lite" and len(notices) == 1


def test_gemini_next_job_tries_main_model_again():
    llm, client = _gemini_with_fallback([_api_error(503), OK_JSON, OK_JSON])
    llm.begin_job()
    llm.generate_json("s", "u", {})
    assert llm.fallback_from == "flash"

    llm.begin_job()  # lần tóm tắt sau
    assert llm.name == "gemini/flash" and llm.fallback_from is None
    llm.generate_json("s", "u", {})
    assert client.requests[-1]["model"] == "flash"


def test_gemini_other_errors_do_not_switch_model():
    # 500 (lỗi tạm thời khác) → thử lại chính mô hình đó như trước
    llm, client = _gemini_with_fallback([_api_error(500), OK_JSON])
    assert llm.generate_json("s", "u", {}) == {"ok": True}
    assert [r["model"] for r in client.requests] == ["flash", "flash"] and llm.fallback_from is None

    # Sai API key → mô hình nào cũng lỗi, không chuyển, không thử lại
    llm, client = _gemini_with_fallback([_api_error(403)])
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        llm.generate_json("s", "u", {})
    assert len(client.requests) == 1


def test_gemini_fallback_also_failing_reports_both():
    llm, client = _gemini_with_fallback([_api_error(504)] + [_api_error(503)] * 3)
    with pytest.raises(LLMError) as e:
        llm.generate_json("s", "u", {})
    msg = str(e.value)
    assert "flash" in msg and "phản hồi quá chậm (504)" in msg and "dự phòng cũng lỗi" in msg and "flash-lite" in msg
    assert [r["model"] for r in client.requests] == ["flash"] + ["flash-lite"] * 3  # mô hình dự phòng vẫn được thử lại


def test_gemini_without_fallback_keeps_waiting_on_main_model():
    client = FakeGeminiClient([_api_error(504)])
    llm = GeminiProvider(api_key="", model="flash", fallback_model="", client=client, retry_wait=0)
    with pytest.raises(LLMError, match="504"):
        llm.generate_json("s", "u", {})
    # Mô hình dự phòng trùng mô hình chính = không có dự phòng
    assert GeminiProvider(api_key="", model="flash", fallback_model="flash", client=client).fallback_model == ""


def test_extract_meeting_reports_fallback():
    answer = json.dumps({"summary": summary(), "action_items": []}, ensure_ascii=False)
    llm, client = _gemini_with_fallback([_api_error(503), answer])
    notices: list[str] = []
    res = extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS, on_notice=notices.append)
    assert res.llm_model == "gemini/flash-lite" and res.fallback_from == "flash" and len(notices) == 1

    # Lần tóm tắt sau: mô hình chính đã hết quá tải → dùng lại mô hình chính
    client.outcomes = [answer]
    res = extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS)
    assert res.llm_model == "gemini/flash" and res.fallback_from is None


# ---------------- Ollama (máy chủ HTTP giả) ----------------


def _ollama(handler, **kw):
    return OllamaProvider("http://localhost:11434/", "qwen2.5:3b", transport=httpx.MockTransport(handler), **kw)


def test_ollama_request_and_response():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        content = json.dumps({"summary": summary(), "action_items": []}, ensure_ascii=False)
        return httpx.Response(200, json={"message": {"content": content}, "prompt_eval_count": 900, "eval_count": 60})

    llm = _ollama(handler, num_ctx=4096)
    out = llm.generate_json("HỆ THỐNG", "NGƯỜI DÙNG", EXTRACTION_SCHEMA)

    assert out["summary"]["topic"] == "Họp tuần nhóm khóa luận"
    assert seen["url"] == "http://localhost:11434/api/chat"
    body = seen["body"]
    assert body["model"] == "qwen2.5:3b" and body["stream"] is False
    assert body["format"] == EXTRACTION_SCHEMA  # ép JSON đúng schema
    assert body["messages"] == [{"role": "system", "content": "HỆ THỐNG"}, {"role": "user", "content": "NGƯỜI DÙNG"}]
    assert body["options"]["num_ctx"] == 4096
    assert llm.last_usage == {"input_tokens": 900, "output_tokens": 60}
    assert llm.name == "ollama/qwen2.5:3b"
    assert llm.max_input_chars == 6144  # mô hình nhỏ → bản ghi dài sẽ bị chia đoạn


def test_ollama_errors_are_actionable():
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(LLMError, match="Không kết nối được Ollama"):
        _ollama(refuse).generate_json("s", "u", {})

    with pytest.raises(LLMError, match="ollama pull qwen2.5:3b"):
        _ollama(lambda r: httpx.Response(404, json={"error": "model not found"})).generate_json("s", "u", {})

    with pytest.raises(LLMError, match="JSON không hợp lệ"):
        _ollama(lambda r: httpx.Response(200, json={"message": {"content": "Xin lỗi, tôi..."}})).generate_json("s", "u", {})


def test_ollama_pipeline_with_small_context():
    """Chạy cả pipeline qua OllamaProvider (máy chủ giả): bản ghi vượt num_ctx → nhiều lần gọi."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if body["format"] == SUMMARY_SCHEMA:
            payload = summary("Đã gộp")
        else:
            payload = {"summary": summary(), "action_items": [item("Viết chương 2", ["Lan"], "thứ Sáu tuần này", LINES[1])]}
        return httpx.Response(200, json={"message": {"content": json.dumps(payload, ensure_ascii=False)}})

    llm = _ollama(handler, num_ctx=100)  # ≈ 150 ký tự mỗi đoạn
    r = extract_meeting(llm, SEGMENTS, MEETING_DATE, MEMBERS)
    assert r.chunk_count >= 2 and len(calls) == r.chunk_count + 1
    assert r.summary["topic"] == "Đã gộp" and r.llm_model == "ollama/qwen2.5:3b"
    assert [(i.title, i.assignee_id, i.due_date) for i in r.items] == [("Viết chương 2", 2, date(2026, 11, 20))]
