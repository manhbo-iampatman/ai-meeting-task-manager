"""Test Giai đoạn 5: duyệt đầu việc nháp, "Đẩy lên bảng" (F17), truy vết nguồn gốc (F18),
giao việc theo tên (F20), tự nhận tên + trưởng nhóm hoàn tác (F21)."""

import pytest

from app.models import MeetingStatus
from app.services import meeting_service as svc
from tests.conftest import auth, register
from tests.test_summarize import LLM_ANSWER, TRANSCRIPT, FakeLLM, _run_job


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch):
    def fake_summarize(meeting):
        meeting.status, meeting.progress, meeting.error = MeetingStatus.SUMMARIZING, 0, None

    monkeypatch.setattr(svc, "enqueue_summarization", fake_summarize)


def _setup(client, monkeypatch, answer=None):
    """Nhóm: Nam (trưởng nhóm), Lan (tải cuộc họp lên), Minh (thành viên thường).
    AI tách 3 việc: Lan (khớp tài khoản), "anh" (người nói tự nhận), "Duy" (chưa có tài khoản)."""
    nam = register(client, "nam@example.com", "Nguyễn Văn Nam")
    lan = register(client, "lan@example.com", "Trần Thị Lan")
    minh = register(client, "minh@example.com", "Lê Quang Minh")
    ws = client.post("/api/workspaces", json={"name": "Nhóm KLTN"}, headers=auth(nam)).json()
    for e in ("lan@example.com", "minh@example.com"):
        client.post(f"/api/workspaces/{ws['id']}/members", json={"email": e}, headers=auth(nam))
    r = client.post(
        f"/api/workspaces/{ws['id']}/meetings",
        data={"title": "Họp tuần 1", "meeting_date": "2026-11-16", "text": TRANSCRIPT},
        headers=auth(lan),
    )
    m = r.json()
    _run_job(monkeypatch, m["id"], FakeLLM(answer))
    return nam, lan, minh, ws, m["id"]


def _get(client, h, mid):
    return client.get(f"/api/meetings/{mid}", headers=auth(h)).json()


def _push(client, h, mid, board_id):
    return client.post(f"/api/meetings/{mid}/push", json={"board_id": board_id}, headers=auth(h))


def _board(client, h, board_id):
    return client.get(f"/api/boards/{board_id}", headers=auth(h)).json()


def _card(client, h, board_id, title):
    return next(t for c in _board(client, h, board_id)["columns"] for t in c["tasks"] if t["title"] == title)


# ---------------- F17: duyệt + đẩy lên bảng ----------------


def test_drafts_keep_unmatched_name_as_text(client, monkeypatch):
    nam, lan, minh, ws, mid = _setup(client, monkeypatch)
    d = _get(client, nam, mid)
    t_lan, t_self, t_duy = d["extracted_tasks"]
    assert t_lan["assignee"]["email"] == "lan@example.com" and t_lan["assignee_name"] is None
    assert t_self["raw_assignee"] == "anh" and t_self["assignee_name"] is None  # đại từ → KHÔNG thành tên chữ
    assert t_duy["assignee"] is None and t_duy["assignee_name"] == "Duy"  # F20
    assert all(t["selected"] for t in d["extracted_tasks"])


def test_only_owner_and_uploader_can_review(client, monkeypatch):
    nam, lan, minh, ws, mid = _setup(client, monkeypatch)
    draft = _get(client, nam, mid)["extracted_tasks"][0]
    assert _get(client, nam, mid)["can_review"] is True  # trưởng nhóm
    assert _get(client, lan, mid)["can_review"] is True  # người tải cuộc họp lên
    assert _get(client, minh, mid)["can_review"] is False  # thành viên thường chỉ xem
    r = client.patch(f"/api/extracted-tasks/{draft['id']}", json={"title": "x"}, headers=auth(minh))
    assert r.status_code == 403
    assert _push(client, minh, mid, ws["boards"][0]["id"]).status_code == 403


def test_edit_draft(client, monkeypatch):
    nam, lan, minh, ws, mid = _setup(client, monkeypatch)
    t_lan, t_self, t_duy = _get(client, lan, mid)["extracted_tasks"]
    url = "/api/extracted-tasks/{}"

    # Người nói tự nhận "anh" → người duyệt chọn Nam
    d = client.patch(url.format(t_self["id"]), json={"assignee_id": nam["_user"]["id"]}, headers=auth(lan)).json()
    x = d["extracted_tasks"][1]
    assert x["assignee"]["email"] == "nam@example.com" and x["assignee_name"] is None and x["assignee_match"] == "manual"

    # Đổi sang tên chữ → bỏ tài khoản; gửi cả hai rỗng → chưa có người làm
    x = client.patch(url.format(t_self["id"]), json={"assignee_name": "  Hùng "}, headers=auth(lan)).json()["extracted_tasks"][1]
    assert x["assignee"] is None and x["assignee_name"] == "Hùng"
    x = client.patch(url.format(t_self["id"]), json={"assignee_id": None, "assignee_name": None}, headers=auth(lan)).json()
    assert x["extracted_tasks"][1]["assignee"] is None and x["extracted_tasks"][1]["assignee_name"] is None

    # Người ngoài nhóm không được chọn làm người làm
    stranger = register(client, "s@example.com")
    r = client.patch(url.format(t_self["id"]), json={"assignee_id": stranger["_user"]["id"]}, headers=auth(lan))
    assert r.status_code == 400

    # Sửa tiêu đề, hạn (hết "ước lượng"), ưu tiên, bỏ tick
    x = client.patch(
        url.format(t_duy["id"]),
        json={"title": "Liên hệ thầy", "due_date": "2026-11-19", "priority": "high", "selected": False},
        headers=auth(lan),
    ).json()["extracted_tasks"][2]
    assert (x["title"], x["due_date"], x["due_approximate"], x["priority"], x["selected"]) == (
        "Liên hệ thầy", "2026-11-19", False, "high", False
    )
    assert client.patch(url.format(t_duy["id"]), json={"title": "  "}, headers=auth(lan)).status_code == 400


def test_push_creates_cards_in_one_go(client, monkeypatch):
    nam, lan, minh, ws, mid = _setup(client, monkeypatch)
    board_id = ws["boards"][0]["id"]
    t_lan, t_self, t_duy = _get(client, lan, mid)["extracted_tasks"]
    client.patch(f"/api/extracted-tasks/{t_self['id']}", json={"selected": False}, headers=auth(lan))

    r = _push(client, lan, mid, board_id)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "done"
    acc = {t["title"]: t for t in d["extracted_tasks"]}
    assert acc["Viết chương 2"]["status"] == "accepted" and acc["Viết chương 2"]["task_board_id"] == board_id
    assert acc["Chuẩn bị bộ dữ liệu thử nghiệm"]["status"] == "rejected"  # bỏ tick → "đã bỏ", vẫn còn để xem

    # Thẻ vào cột ĐẦU TIÊN, giữ người làm / tên chữ / hạn / ưu tiên, nhớ cuộc họp nguồn
    b = _board(client, nam, board_id)
    todo = b["columns"][0]["tasks"]
    assert [t["title"] for t in todo] == ["Viết chương 2", "Liên hệ thầy hướng dẫn"]
    assert todo[0]["assignee"]["email"] == "lan@example.com" and todo[0]["due_date"] == "2026-11-20"
    assert todo[0]["priority"] == "high" and todo[0]["meeting_id"] == mid
    assert todo[1]["assignee"] is None and todo[1]["assignee_name"] == "Duy"

    # Lan tự đẩy việc của mình → không tự báo cho mình; F18: thẻ biết nguồn gốc
    t = client.get(f"/api/tasks/{todo[0]['id']}", headers=auth(nam)).json()
    assert t["source"]["meeting_id"] == mid and t["source"]["meeting_title"] == "Họp tuần 1"
    assert t["source"]["evidence_quote"].startswith("Lan viết chương hai")

    # Không còn việc nào được tick → không đẩy được nữa
    assert _push(client, lan, mid, board_id).status_code == 400

    # Tick lại việc "đã bỏ" rồi đẩy thêm lần nữa
    x = client.patch(f"/api/extracted-tasks/{t_self['id']}", json={"selected": True}, headers=auth(lan)).json()
    assert x["extracted_tasks"][1]["status"] == "pending"
    assert _push(client, lan, mid, board_id).status_code == 200
    assert len(_board(client, nam, board_id)["columns"][0]["tasks"]) == 3

    # Việc đã lên bảng thì không sửa ở màn hình duyệt nữa
    r = client.patch(f"/api/extracted-tasks/{t_lan['id']}", json={"title": "x"}, headers=auth(lan))
    assert r.status_code == 409


def test_push_notifies_assignee(client, monkeypatch):
    nam, lan, minh, ws, mid = _setup(client, monkeypatch)
    assert _push(client, nam, mid, ws["boards"][0]["id"]).status_code == 200
    items = client.get("/api/notifications", headers=auth(lan)).json()["items"]
    assert [n["payload"]["task_title"] for n in items if n["type"] == "task_assigned"] == ["Viết chương 2"]


def test_push_to_board_of_other_workspace_is_rejected(client, monkeypatch):
    nam, lan, minh, ws, mid = _setup(client, monkeypatch)
    other = client.post("/api/workspaces", json={"name": "Nhóm khác"}, headers=auth(nam)).json()
    r = _push(client, nam, mid, other["boards"][0]["id"])
    assert r.status_code == 400
    # Không có thẻ nào bị tạo dở dang
    assert _board(client, nam, other["boards"][0]["id"])["columns"][0]["tasks"] == []
    assert all(t["status"] == "pending" for t in _get(client, nam, mid)["extracted_tasks"])


def test_resummarize_after_push_marks_duplicates(client, monkeypatch):
    nam, lan, minh, ws, mid = _setup(client, monkeypatch)
    board_id = ws["boards"][0]["id"]
    _push(client, lan, mid, board_id)

    answer = {
        "summary": LLM_ANSWER["summary"],
        "action_items": LLM_ANSWER["action_items"][:1]  # Lan viết chương 2 — đã có trên bảng
        + [{"task": "Làm slide báo cáo", "assignees": ["Minh"], "due": "", "priority": "medium",
            "evidence": "Duy liên hệ thầy hướng dẫn trong ngày mai."}],
    }
    assert client.post(f"/api/meetings/{mid}/summarize", headers=auth(lan)).status_code == 200
    _run_job(monkeypatch, mid, FakeLLM(answer))

    d = _get(client, lan, mid)
    assert d["status"] == "review"
    pushed = [t for t in d["extracted_tasks"] if t["status"] == "accepted"]
    new = [t for t in d["extracted_tasks"] if t["status"] != "accepted"]
    assert len(pushed) == 3  # việc đã đẩy được GIỮ lại (truy vết)
    dup, fresh = new
    assert dup["title"] == "Viết chương 2" and dup["selected"] is False and dup["duplicate_of_task_id"] is not None
    assert fresh["title"] == "Làm slide báo cáo" and fresh["selected"] is True and fresh["duplicate_of_task_id"] is None

    assert _push(client, lan, mid, board_id).status_code == 200
    titles = [t["title"] for t in _board(client, nam, board_id)["columns"][0]["tasks"]]
    assert titles.count("Viết chương 2") == 1 and "Làm slide báo cáo" in titles


# ---------------- F20: giao theo tên trên bảng ----------------


def test_manual_task_with_name_assignee(client):
    nam = register(client, "nam@example.com", "Nguyễn Văn Nam")
    lan = register(client, "lan@example.com", "Trần Thị Lan")
    ws = client.post("/api/workspaces", json={"name": "N"}, headers=auth(nam)).json()
    client.post(f"/api/workspaces/{ws['id']}/members", json={"email": "lan@example.com"}, headers=auth(nam))
    b = _board(client, nam, ws["boards"][0]["id"])
    col = b["columns"][0]["id"]

    t = client.post(f"/api/boards/{b['id']}/tasks", json={"column_id": col, "title": "Làm poster", "assignee_name": "  Su  "},
                    headers=auth(nam)).json()
    assert t["assignee"] is None and t["assignee_name"] == "Su" and t["meeting_id"] is None

    # Chọn thành viên → bỏ tên chữ; gõ tên → bỏ thành viên
    t2 = client.patch(f"/api/tasks/{t['id']}", json={"assignee_id": lan["_user"]["id"]}, headers=auth(nam)).json()
    assert t2["assignee"]["email"] == "lan@example.com" and t2["assignee_name"] is None
    t3 = client.patch(f"/api/tasks/{t['id']}", json={"assignee_name": "Su"}, headers=auth(nam)).json()
    assert t3["assignee"] is None and t3["assignee_name"] == "Su"
    t4 = client.patch(f"/api/tasks/{t['id']}", json={"assignee_id": None, "assignee_name": None}, headers=auth(nam)).json()
    assert t4["assignee"] is None and t4["assignee_name"] is None and t4["source"] is None

    # Gửi cả tài khoản lẫn tên khi tạo → lấy tài khoản
    t5 = client.post(f"/api/boards/{b['id']}/tasks",
                     json={"column_id": col, "title": "x", "assignee_id": lan["_user"]["id"], "assignee_name": "Su"},
                     headers=auth(nam)).json()
    assert t5["assignee"]["email"] == "lan@example.com" and t5["assignee_name"] is None


# ---------------- F21: tự nhận tên ----------------


def _pending(client, h, ws_id):
    return client.get(f"/api/workspaces/{ws_id}/pending-names", headers=auth(h)).json()


def test_pending_names_group_spellings(client):
    nam = register(client, "nam@example.com", "Nguyễn Văn Nam")
    ws = client.post("/api/workspaces", json={"name": "N"}, headers=auth(nam)).json()
    b = _board(client, nam, ws["boards"][0]["id"])
    col = b["columns"][0]["id"]
    for i, name in enumerate(["Duy", "anh Duy", "duy", "Năm", "Nam Anh"]):
        client.post(f"/api/boards/{b['id']}/tasks", json={"column_id": col, "title": f"Việc {i}", "assignee_name": name},
                    headers=auth(nam))
    names = {p["name"]: p for p in _pending(client, nam, ws["id"])}
    # "Duy", "anh Duy", "duy" là MỘT tên; "Năm" khác "Nam Anh" (giữ dấu)
    assert set(names) == {"Duy", "Năm", "Nam Anh"}
    assert len(names["Duy"]["tasks"]) == 3 and set(names["Duy"]["variants"]) == {"Duy", "duy"}


def test_claim_and_undo(client, monkeypatch):
    nam, lan, minh, ws, mid = _setup(client, monkeypatch)
    board_id = ws["boards"][0]["id"]
    _push(client, lan, mid, board_id)  # thẻ "Liên hệ thầy hướng dẫn" mang tên chữ "Duy"

    # Duy đăng ký, vào nhóm bằng link mời → thấy tên "Duy" đang chờ, được gợi ý
    duy = register(client, "duy@example.com", "Phạm Đức Duy")
    assert client.post("/api/workspaces/join", json={"invite_code": ws["invite_code"]}, headers=auth(duy)).status_code == 200
    pend = _pending(client, duy, ws["id"])
    assert [(p["name"], p["suggested"], len(p["tasks"])) for p in pend] == [("Duy", True, 1)]
    assert _pending(client, minh, ws["id"])[0]["suggested"] is False  # mọi thành viên thấy, nhưng không gợi ý cho Minh

    r = client.post(f"/api/workspaces/{ws['id']}/pending-names/claim", json={"key": pend[0]["key"]}, headers=auth(duy))
    assert r.status_code == 200, r.text
    claim = r.json()
    assert (claim["name"], claim["task_count"], claim["added_nickname"]) == ("Duy", 1, "Duy")

    # Có hiệu lực ngay: thẻ chuyển cho Duy, tên thành biệt danh, hết trong danh sách chờ
    card = _card(client, nam, board_id, "Liên hệ thầy hướng dẫn")
    assert card["assignee"]["email"] == "duy@example.com" and card["assignee_name"] is None
    members = client.get(f"/api/workspaces/{ws['id']}", headers=auth(nam)).json()["members"]
    assert next(m for m in members if m["user"]["email"] == "duy@example.com")["nicknames"] == ["Duy"]
    assert _pending(client, duy, ws["id"]) == []
    assert client.get("/api/me/tasks", headers=auth(duy)).json()[0]["title"] == "Liên hệ thầy hướng dẫn"
    r = client.post(f"/api/workspaces/{ws['id']}/pending-names/claim", json={"key": "duy"}, headers=auth(minh))
    assert r.status_code == 404  # đã có người nhận

    # Một thông báo TỔNG cho Duy; trưởng nhóm được báo kèm thông tin để hoàn tác
    n_duy = client.get("/api/notifications", headers=auth(duy)).json()["items"]
    assert [n["payload"]["task_count"] for n in n_duy if n["type"] == "name_claimed"] == [1]
    # Việc vừa nhận có hạn 17/11/2026 (đã tới / đã qua) → Duy được nhắc hạn như mọi việc khác của mình
    assert {"task_due_soon", "task_overdue"} & {n["type"] for n in n_duy}
    n_nam = [n for n in client.get("/api/notifications", headers=auth(nam)).json()["items"] if n["type"] == "name_claimed_member"]
    assert len(n_nam) == 1 and n_nam[0]["payload"]["claimer_name"] == "Phạm Đức Duy"

    # Chỉ trưởng nhóm hoàn tác được
    assert client.post(f"/api/name-claims/{claim['id']}/undo", headers=auth(lan)).status_code == 403
    assert client.post(f"/api/name-claims/{claim['id']}/undo", headers=auth(nam)).status_code == 200
    card = _card(client, nam, board_id, "Liên hệ thầy hướng dẫn")
    assert card["assignee"] is None and card["assignee_name"] == "Duy"
    members = client.get(f"/api/workspaces/{ws['id']}", headers=auth(nam)).json()["members"]
    assert next(m for m in members if m["user"]["email"] == "duy@example.com")["nicknames"] == []
    assert [p["name"] for p in _pending(client, duy, ws["id"])] == ["Duy"]
    n_nam = [n for n in client.get("/api/notifications", headers=auth(nam)).json()["items"] if n["type"] == "name_claimed_member"]
    assert n_nam[0]["payload"]["undone"] is True
    assert "name_claim_undone" in [n["type"] for n in client.get("/api/notifications", headers=auth(duy)).json()["items"]]
    assert client.post(f"/api/name-claims/{claim['id']}/undo", headers=auth(nam)).status_code == 409


def test_claim_applies_to_drafts_and_teaches_ai(client, monkeypatch):
    """Nhận tên khi việc còn là NHÁP → ghép luôn; cuộc họp SAU AI tự hiểu tên đó là ai (nhờ biệt danh)."""
    nam, lan, minh, ws, mid = _setup(client, monkeypatch)
    duy = register(client, "duy@example.com", "Phạm Đức Duy")
    client.post("/api/workspaces/join", json={"invite_code": ws["invite_code"]}, headers=auth(duy))

    # Minh bị gọi là "Su" trong họp → AI không ghép được
    answer = {"summary": LLM_ANSWER["summary"], "action_items": [
        {"task": "Làm poster", "assignees": ["Su"], "due": "", "priority": "medium", "evidence": ""}]}
    client.post(f"/api/meetings/{mid}/summarize", headers=auth(lan))
    _run_job(monkeypatch, mid, FakeLLM(answer))
    assert _get(client, lan, mid)["extracted_tasks"][0]["assignee_name"] == "Su"

    claim = client.post(f"/api/workspaces/{ws['id']}/pending-names/claim", json={"key": "su"}, headers=auth(minh)).json()
    assert claim["draft_count"] == 1 and claim["task_count"] == 0
    draft = _get(client, lan, mid)["extracted_tasks"][0]
    assert draft["assignee"]["email"] == "minh@example.com" and draft["assignee_match"] == "claimed"

    # Đẩy lên bảng → thẻ của Minh. Trưởng nhóm hoàn tác → thẻ trở lại tên "Su"
    _push(client, lan, mid, ws["boards"][0]["id"])
    client.post(f"/api/name-claims/{claim['id']}/undo", headers=auth(nam))
    card = _board(client, nam, ws["boards"][0]["id"])["columns"][0]["tasks"][0]
    assert card["assignee"] is None and card["assignee_name"] == "Su"

    # Nhận lại; cuộc họp sau có "Su" → AI ghép thẳng vào Minh qua biệt danh
    client.post(f"/api/workspaces/{ws['id']}/pending-names/claim", json={"key": "su"}, headers=auth(minh))
    r = client.post(
        f"/api/workspaces/{ws['id']}/meetings",
        data={"title": "Họp tuần 2", "meeting_date": "2026-11-23", "text": TRANSCRIPT},
        headers=auth(lan),
    )
    _run_job(monkeypatch, r.json()["id"], FakeLLM(answer))
    t = _get(client, lan, r.json()["id"])["extracted_tasks"][0]
    assert t["assignee"]["email"] == "minh@example.com" and t["assignee_name"] is None


# ---------------- Sửa sau khi dùng thử (18/11/2026) ----------------


def test_pending_list_hidden_after_claim(client):
    """Đã nhận một tên thì không thấy danh sách nữa; bị hoàn tác thì thấy lại."""
    nam = register(client, "nam@example.com", "Nguyễn Văn Nam")
    minh = register(client, "minh@example.com", "Lê Quang Minh")
    lan = register(client, "lan@example.com", "Trần Thị Lan")
    ws = client.post("/api/workspaces", json={"name": "N"}, headers=auth(nam)).json()
    for h in (minh, lan):
        client.post("/api/workspaces/join", json={"invite_code": ws["invite_code"]}, headers=auth(h))
    b = _board(client, nam, ws["boards"][0]["id"])
    for name in ("Su", "Duy"):
        client.post(f"/api/boards/{b['id']}/tasks", json={"column_id": b["columns"][0]["id"], "title": f"Việc {name}",
                                                          "assignee_name": name}, headers=auth(nam))

    claim = client.post(f"/api/workspaces/{ws['id']}/pending-names/claim", json={"key": "su"}, headers=auth(minh)).json()
    assert _pending(client, minh, ws["id"]) == []  # Minh đã nhận "Su" → ẩn danh sách
    assert [p["name"] for p in _pending(client, lan, ws["id"])] == ["Duy"]  # người chưa nhận vẫn thấy
    client.post(f"/api/name-claims/{claim['id']}/undo", headers=auth(nam))
    assert {p["name"] for p in _pending(client, minh, ws["id"])} == {"Su", "Duy"}  # bị hoàn tác → thấy lại


def test_pending_draft_reports_its_status(client, monkeypatch):
    nam, lan, minh, ws, mid = _setup(client, monkeypatch)
    t_duy = _get(client, lan, mid)["extracted_tasks"][2]
    client.patch(f"/api/extracted-tasks/{t_duy['id']}", json={"selected": False}, headers=auth(lan))
    assert _pending(client, minh, ws["id"])[0]["drafts"][0]["status"] == "pending"
    _push(client, lan, mid, ws["boards"][0]["id"])  # việc của Duy bị bỏ tick → "đã bỏ"
    assert _pending(client, minh, ws["id"])[0]["drafts"][0]["status"] == "rejected"


def test_only_assignee_creator_or_owner_can_change_a_card(client):
    """Kéo thả / sửa / xóa thẻ: người làm, người tạo thẻ, trưởng nhóm. Người khác chỉ xem + bình luận."""
    nam = register(client, "nam@example.com", "Nguyễn Văn Nam")
    lan = register(client, "lan@example.com", "Trần Thị Lan")
    minh = register(client, "minh@example.com", "Lê Quang Minh")
    ws = client.post("/api/workspaces", json={"name": "N"}, headers=auth(nam)).json()
    for h in (lan, minh):
        client.post("/api/workspaces/join", json={"invite_code": ws["invite_code"]}, headers=auth(h))
    b = _board(client, nam, ws["boards"][0]["id"])
    assert b["owner_id"] == nam["_user"]["id"]
    todo, done = b["columns"][0]["id"], b["columns"][2]["id"]

    def can(h, t):
        """(kéo, sửa) có được không."""
        mv = client.post(f"/api/tasks/{t}/move", json={"column_id": done, "index": 0}, headers=auth(h)).status_code
        ed = client.patch(f"/api/tasks/{t}", json={"priority": "high"}, headers=auth(h)).status_code
        return mv == 200, ed == 200

    # Nam tạo, giao cho Lan → Nam (trưởng nhóm + người tạo) và Lan (người làm) được; Minh thì không
    t1 = client.post(f"/api/boards/{b['id']}/tasks", json={"column_id": todo, "title": "Việc của Lan",
                                                           "assignee_id": lan["_user"]["id"]}, headers=auth(nam)).json()["id"]
    assert can(lan, t1) == (True, True) and can(nam, t1) == (True, True)
    assert can(minh, t1) == (False, False)
    assert client.delete(f"/api/tasks/{t1}", headers=auth(minh)).status_code == 403
    # ...nhưng Minh vẫn xem và bình luận được
    assert client.get(f"/api/tasks/{t1}", headers=auth(minh)).status_code == 200
    assert client.post(f"/api/tasks/{t1}/comments", json={"content": "Cố lên"}, headers=auth(minh)).status_code == 201

    # Lan tự tạo thẻ chưa giao → Lan (người tạo) + Nam (trưởng nhóm) được, Minh không
    t2 = client.post(f"/api/boards/{b['id']}/tasks", json={"column_id": todo, "title": "Việc chung"},
                     headers=auth(lan)).json()["id"]
    assert can(lan, t2) == (True, True) and can(nam, t2) == (True, True) and can(minh, t2) == (False, False)

    # Thẻ giao theo tên chữ (chưa có tài khoản): chỉ người tạo + trưởng nhóm
    t3 = client.post(f"/api/boards/{b['id']}/tasks", json={"column_id": todo, "title": "Việc của Su",
                                                           "assignee_name": "Su"}, headers=auth(nam)).json()["id"]
    assert can(lan, t3) == (False, False) and can(nam, t3) == (True, True)

    # Người làm giao lại cho người khác → mất quyền; người tạo thẻ (Lan) xóa được thẻ của mình
    client.patch(f"/api/tasks/{t1}", json={"assignee_id": minh["_user"]["id"]}, headers=auth(lan))
    assert can(lan, t1) == (False, False) and can(minh, t1) == (True, True)
    assert client.delete(f"/api/tasks/{t2}", headers=auth(lan)).status_code == 204
