"""bon cot mac dinh: them cot Cho duyet

Bảng mới tạo có 4 cột: Cần làm / Đang làm / Chờ duyệt / Hoàn thành (trước đây 3 cột).
Migration này KHÔNG đổi cấu trúc bảng, chỉ sửa dữ liệu: bảng nào vẫn còn đúng 3 cột gốc thì được chèn
thêm cột "Chờ duyệt" vào trước cột "Hoàn thành". Bảng người dùng đã tự đổi tên / thêm / xóa cột thì giữ nguyên.

Revision ID: b3f1c2a94e07
Revises: 7433f594207d
Create Date: 2026-11-18 21:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f1c2a94e07'
down_revision: Union[str, Sequence[str], None] = '7433f594207d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = [("Cần làm", False), ("Đang làm", False), ("Hoàn thành", True)]
NEW_NAME = "Chờ duyệt"


def _columns_by_board(bind) -> dict[int, list]:
    rows = bind.execute(sa.text("SELECT id, board_id, name, position, is_done FROM columns ORDER BY board_id, position, id"))
    boards: dict[int, list] = {}
    for r in rows:
        boards.setdefault(r.board_id, []).append(r)
    return boards


def upgrade() -> None:
    bind = op.get_bind()
    for board_id, cols in _columns_by_board(bind).items():
        if [(c.name, c.is_done) for c in cols] != OLD:
            continue  # bảng đã được người dùng chỉnh cột → không đụng vào
        done = cols[2]
        bind.execute(sa.text("UPDATE columns SET position = :p WHERE id = :id"), {"p": done.position + 1, "id": done.id})
        bind.execute(
            sa.text("INSERT INTO columns (board_id, name, position, is_done) VALUES (:b, :n, :p, false)"),
            {"b": board_id, "n": NEW_NAME, "p": done.position},
        )


def downgrade() -> None:
    """Gỡ cột "Chờ duyệt" đã chèn — chỉ khi cột đó đang trống và bảng vẫn đúng 4 cột mặc định."""
    bind = op.get_bind()
    expected = [OLD[0], OLD[1], (NEW_NAME, False), OLD[2]]
    for cols in _columns_by_board(bind).values():
        if [(c.name, c.is_done) for c in cols] != expected:
            continue
        review = cols[2]
        if bind.execute(sa.text("SELECT count(*) FROM tasks WHERE column_id = :id"), {"id": review.id}).scalar():
            continue
        bind.execute(sa.text("DELETE FROM columns WHERE id = :id"), {"id": review.id})
        bind.execute(sa.text("UPDATE columns SET position = :p WHERE id = :id"), {"p": review.position, "id": cols[3].id})
