"""Tạo dữ liệu DEMO: 3 tài khoản, 1 nhóm, 1 bảng với vài công việc mẫu.

Chạy (trong thư mục backend):
    .venv\\Scripts\\python scripts\\seed_demo.py

Tài khoản demo (CHỈ dùng trên máy phát triển):
    nam@example.com / demo1234   (trưởng nhóm)
    lan@example.com / demo1234
    minh@example.com / demo1234
Chạy lại nhiều lần không bị trùng: nếu nhóm demo đã có thì bỏ qua.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Task, User, Workspace, WorkspaceMember  # noqa: E402
from app.services.board_service import create_board_with_default_columns  # noqa: E402

DEMO_PASSWORD = "demo1234"
USERS = [
    ("nam@example.com", "Nguyễn Văn Nam", ["Nam", "anh Nam"]),
    ("lan@example.com", "Trần Thị Lan", ["Lan", "chị Lan"]),
    ("minh@example.com", "Lê Quang Minh", ["Minh"]),
]


def main() -> None:
    with SessionLocal() as db:
        users: list[User] = []
        for email, name, _ in USERS:
            u = db.scalar(select(User).where(User.email == email))
            if u is None:
                u = User(email=email, full_name=name, password_hash=hash_password(DEMO_PASSWORD))
                db.add(u)
                db.flush()
            users.append(u)

        if db.scalar(select(Workspace).where(Workspace.invite_code == "demo-kltn")):
            print("Dữ liệu demo đã có sẵn — bỏ qua.")
            db.commit()
            return

        ws = Workspace(name="Nhóm KLTN (demo)", owner_id=users[0].id, invite_code="demo-kltn")
        db.add(ws)
        db.flush()
        for i, (u, (_, _, nicks)) in enumerate(zip(users, USERS, strict=True)):
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role="owner" if i == 0 else "member", nicknames=nicks))

        board = create_board_with_default_columns(db, ws.id, "Bảng chính")
        todo, doing, _review, done = board.columns
        today = date.today()
        samples = [
            (todo, "Thiết kế cơ sở dữ liệu", users[0], today + timedelta(days=5), "high"),
            (todo, "Chuẩn bị slide demo cho khách hàng", users[1], today + timedelta(days=1), "medium"),
            (todo, "Viết chương 2 – Cơ sở lý thuyết", None, None, "low"),
            (doing, "Sửa lỗi đăng nhập", users[2], today, "high"),
            (doing, "Khảo sát Trello, Notion AI, Otter.ai", users[1], today - timedelta(days=1), "medium"),
            (done, "Cài Docker + PostgreSQL", users[0], today - timedelta(days=2), "medium"),
        ]
        counters: dict[int, int] = {}
        for col, title, assignee, due, prio in samples:
            counters[col.id] = counters.get(col.id, 0) + 1
            db.add(
                Task(
                    board_id=board.id,
                    column_id=col.id,
                    title=title,
                    assignee_id=assignee.id if assignee else None,
                    due_date=due,
                    priority=prio,
                    position=counters[col.id] * 1000.0,
                    created_by=users[0].id,
                )
            )
        db.commit()
        print(f"Đã tạo nhóm demo (id={ws.id}), bảng (id={board.id}), {len(samples)} công việc.")
        print("Đăng nhập: nam@example.com / lan@example.com / minh@example.com — mật khẩu: demo1234")


if __name__ == "__main__":
    main()
