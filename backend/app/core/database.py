"""Kết nối PostgreSQL bằng SQLAlchemy 2.

- engine: "cổng" kết nối tới CSDL, giữ một pool kết nối dùng lại.
- SessionLocal: tạo phiên làm việc (session) cho mỗi request.
- Base: lớp cha của mọi model (bảng) — các giai đoạn sau sẽ kế thừa.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # kiểm tra kết nối còn sống trước khi dùng
    connect_args={"connect_timeout": 3},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """Dependency của FastAPI: mở session đầu request, đóng khi xong."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
