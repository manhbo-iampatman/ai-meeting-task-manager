from datetime import date, timedelta

from tests.conftest import auth, register


def _setup(client):
    owner = register(client, "owner@example.com", "Trưởng Nhóm")
    ws = client.post("/api/workspaces", json={"name": "Nhóm KLTN"}, headers=auth(owner)).json()
    return owner, ws


def test_create_workspace_has_default_board(client):
    owner, ws = _setup(client)
    assert ws["my_role"] == "owner"
    assert len(ws["boards"]) == 1
    board = client.get(f"/api/boards/{ws['boards'][0]['id']}", headers=auth(owner)).json()
    assert [c["name"] for c in board["columns"]] == ["Cần làm", "Đang làm", "Chờ duyệt", "Hoàn thành"]
    assert [c["is_done"] for c in board["columns"]] == [False, False, False, True]


def test_non_member_cannot_access(client):
    owner, ws = _setup(client)
    stranger = register(client, "stranger@example.com")
    board_id = ws["boards"][0]["id"]
    assert client.get(f"/api/workspaces/{ws['id']}", headers=auth(stranger)).status_code == 404
    assert client.get(f"/api/boards/{board_id}", headers=auth(stranger)).status_code == 404


def test_join_by_invite_code_and_permissions(client):
    owner, ws = _setup(client)
    member = register(client, "mem@example.com", "Thành Viên")
    r = client.post("/api/workspaces/join", json={"invite_code": ws["invite_code"]}, headers=auth(member))
    assert r.status_code == 200
    assert r.json()["my_role"] == "member"
    assert len(r.json()["members"]) == 2

    # Thành viên thường không được đổi tên nhóm
    assert client.patch(f"/api/workspaces/{ws['id']}", json={"name": "X"}, headers=auth(member)).status_code == 403
    # Nhưng được tự sửa biệt danh của mình
    uid = member["_user"]["id"]
    r = client.patch(
        f"/api/workspaces/{ws['id']}/members/{uid}", json={"nicknames": ["Mem", " mem ", "Bé Mem"]}, headers=auth(member)
    )
    assert r.status_code == 200
    assert r.json()["nicknames"] == ["Mem", "Bé Mem"]  # bỏ trùng không phân biệt hoa thường

    # Đổi mã mời → mã cũ hết hiệu lực
    old = ws["invite_code"]
    client.post(f"/api/workspaces/{ws['id']}/invite-code", headers=auth(owner))
    late = register(client, "late@example.com")
    assert client.post("/api/workspaces/join", json={"invite_code": old}, headers=auth(late)).status_code == 404


def test_task_crud_move_and_order(client):
    owner, ws = _setup(client)
    board_id = ws["boards"][0]["id"]
    board = client.get(f"/api/boards/{board_id}", headers=auth(owner)).json()
    todo, doing = board["columns"][0]["id"], board["columns"][1]["id"]

    ids = []
    for title in ["A", "B", "C"]:
        r = client.post(f"/api/boards/{board_id}/tasks", json={"column_id": todo, "title": title}, headers=auth(owner))
        assert r.status_code == 201
        ids.append(r.json()["id"])

    def titles(col_idx):
        b = client.get(f"/api/boards/{board_id}", headers=auth(owner)).json()
        return [t["title"] for t in b["columns"][col_idx]["tasks"]]

    assert titles(0) == ["A", "B", "C"]

    # Kéo C lên đầu cột
    client.post(f"/api/tasks/{ids[2]}/move", json={"column_id": todo, "index": 0}, headers=auth(owner))
    assert titles(0) == ["C", "A", "B"]

    # Kéo A sang cột "Đang làm"
    client.post(f"/api/tasks/{ids[0]}/move", json={"column_id": doing, "index": 0}, headers=auth(owner))
    assert titles(0) == ["C", "B"]
    assert titles(1) == ["A"]

    # Kéo B xuống cuối (index lớn hơn số thẻ → đặt cuối)
    client.post(f"/api/tasks/{ids[1]}/move", json={"column_id": todo, "index": 99}, headers=auth(owner))
    assert titles(0) == ["C", "B"]

    # Sửa và xóa
    r = client.patch(f"/api/tasks/{ids[0]}", json={"title": "A2", "priority": "high"}, headers=auth(owner))
    assert r.json()["title"] == "A2" and r.json()["priority"] == "high"
    assert client.delete(f"/api/tasks/{ids[0]}", headers=auth(owner)).status_code == 204
    assert titles(1) == []


def test_many_moves_keep_order(client):
    """Chèn liên tục vào cùng 1 chỗ → kích hoạt đánh số lại (rebalance) mà thứ tự vẫn đúng."""
    owner, ws = _setup(client)
    board_id = ws["boards"][0]["id"]
    todo = client.get(f"/api/boards/{board_id}", headers=auth(owner)).json()["columns"][0]["id"]
    a = client.post(f"/api/boards/{board_id}/tasks", json={"column_id": todo, "title": "first"}, headers=auth(owner))
    client.post(f"/api/boards/{board_id}/tasks", json={"column_id": todo, "title": "last"}, headers=auth(owner))
    for i in range(60):
        t = client.post(f"/api/boards/{board_id}/tasks", json={"column_id": todo, "title": f"x{i}"}, headers=auth(owner))
        client.post(f"/api/tasks/{t.json()['id']}/move", json={"column_id": todo, "index": 1}, headers=auth(owner))
    b = client.get(f"/api/boards/{board_id}", headers=auth(owner)).json()
    tasks = b["columns"][0]["tasks"]
    assert tasks[0]["id"] == a.json()["id"]
    assert tasks[-1]["title"] == "last"
    assert tasks[1]["title"] == "x59"
    positions = [t["position"] for t in tasks]
    assert positions == sorted(positions) and len(set(positions)) == len(positions)


def test_assign_notification_and_my_tasks(client):
    owner, ws = _setup(client)
    member = register(client, "mem@example.com", "Thành Viên")
    client.post("/api/workspaces/join", json={"invite_code": ws["invite_code"]}, headers=auth(member))
    board_id = ws["boards"][0]["id"]
    cols = client.get(f"/api/boards/{board_id}", headers=auth(owner)).json()["columns"]
    uid = member["_user"]["id"]

    r = client.post(
        f"/api/boards/{board_id}/tasks",
        json={"column_id": cols[0]["id"], "title": "Viết báo cáo", "assignee_id": uid, "due_date": str(date.today())},
        headers=auth(owner),
    )
    task_id = r.json()["id"]

    notes = client.get("/api/notifications", headers=auth(member)).json()
    types = sorted(n["type"] for n in notes["items"])
    assert types == ["task_assigned", "task_due_soon"]
    assert notes["unread_count"] == 2
    # Gọi lại không sinh thông báo trùng
    assert client.get("/api/notifications", headers=auth(member)).json()["unread_count"] == 2

    mine = client.get("/api/me/tasks", headers=auth(member)).json()
    assert [t["title"] for t in mine] == ["Viết báo cáo"]
    assert mine[0]["workspace_name"] == "Nhóm KLTN"

    # Chuyển sang cột Hoàn thành → không còn trong "việc của tôi"
    client.post(f"/api/tasks/{task_id}/move", json={"column_id": cols[-1]["id"], "index": 0}, headers=auth(member))
    assert client.get("/api/me/tasks", headers=auth(member)).json() == []

    client.post("/api/notifications/read-all", headers=auth(member))
    assert client.get("/api/notifications", headers=auth(member)).json()["unread_count"] == 0


def test_overdue_and_cannot_assign_outsider(client):
    owner, ws = _setup(client)
    outsider = register(client, "out@example.com")
    board_id = ws["boards"][0]["id"]
    col = client.get(f"/api/boards/{board_id}", headers=auth(owner)).json()["columns"][0]["id"]
    r = client.post(
        f"/api/boards/{board_id}/tasks",
        json={"column_id": col, "title": "X", "assignee_id": outsider["_user"]["id"]},
        headers=auth(owner),
    )
    assert r.status_code == 400

    client.post(
        f"/api/boards/{board_id}/tasks",
        json={
            "column_id": col,
            "title": "Trễ",
            "assignee_id": owner["_user"]["id"],
            "due_date": str(date.today() - timedelta(days=2)),
        },
        headers=auth(owner),
    )
    notes = client.get("/api/notifications", headers=auth(owner)).json()["items"]
    assert [n["type"] for n in notes] == ["task_overdue"]  # tự giao cho mình → không có task_assigned


def test_comments_and_remove_member_unassigns(client):
    owner, ws = _setup(client)
    member = register(client, "mem@example.com")
    client.post("/api/workspaces/join", json={"invite_code": ws["invite_code"]}, headers=auth(member))
    board_id = ws["boards"][0]["id"]
    col = client.get(f"/api/boards/{board_id}", headers=auth(owner)).json()["columns"][0]["id"]
    uid = member["_user"]["id"]
    t = client.post(
        f"/api/boards/{board_id}/tasks", json={"column_id": col, "title": "T", "assignee_id": uid}, headers=auth(owner)
    ).json()

    c = client.post(f"/api/tasks/{t['id']}/comments", json={"content": "Em làm xong rồi"}, headers=auth(member))
    assert c.status_code == 201
    assert client.delete(f"/api/comments/{c.json()['id']}", headers=auth(owner)).status_code == 403
    detail = client.get(f"/api/tasks/{t['id']}", headers=auth(owner)).json()
    assert detail["comment_count"] == 1 and detail["column_name"] == "Cần làm"

    assert client.delete(f"/api/workspaces/{ws['id']}/members/{uid}", headers=auth(owner)).status_code == 204
    assert client.get(f"/api/tasks/{t['id']}", headers=auth(owner)).json()["assignee"] is None


def test_websocket_requires_membership(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    owner, ws = _setup(client)
    stranger = register(client, "s@example.com")
    board_id = ws["boards"][0]["id"]
    token_owner = owner["Authorization"].split()[1]
    token_stranger = stranger["Authorization"].split()[1]

    # Token gửi trong tin nhắn đầu tiên, KHÔNG đặt trên link (link bị ghi vào log)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/ws/boards/{board_id}") as s:
            s.send_json({"type": "auth", "token": token_stranger})
            s.receive_text()
    # Token trên link kiểu cũ → không được tính, gửi tin nhắn khác "auth" → bị đóng
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/ws/boards/{board_id}?token={token_owner}") as s:
            s.send_text("ping")
            s.receive_text()

    with client.websocket_connect(f"/api/ws/boards/{board_id}") as s:
        s.send_json({"type": "auth", "token": token_owner})
        assert s.receive_json() == {"type": "auth_ok"}
        col = client.get(f"/api/boards/{board_id}", headers=auth(owner)).json()["columns"][0]["id"]
        client.post(f"/api/boards/{board_id}/tasks", json={"column_id": col, "title": "Mới"}, headers=auth(owner))
        msg = s.receive_json()
        assert msg["type"] == "board_updated" and msg["board_id"] == board_id
