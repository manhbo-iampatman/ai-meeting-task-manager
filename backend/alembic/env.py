"""Cấu hình Alembic — công cụ quản lý migration (phiên bản cấu trúc CSDL).

Các lệnh hay dùng (trong thư mục backend, đã kích hoạt .venv):
    alembic revision --autogenerate -m "mô tả"   # so model với CSDL, sinh file migration
    alembic upgrade head                          # áp dụng mọi migration chưa chạy
    alembic downgrade -1                          # quay lại 1 phiên bản
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app import models  # noqa: F401 — import để đăng ký mọi bảng vào Base.metadata
from app.core.config import get_settings
from app.core.database import Base

config = context.config
# Lấy chuỗi kết nối từ .env thay vì ghi cứng trong alembic.ini
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
