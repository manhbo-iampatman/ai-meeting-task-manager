"""Token / vé trên đường link không được lọt vào log của uvicorn."""

import logging

from app.core import log_redact


def test_redact_hides_token_and_ticket():
    line = '127.0.0.1:5000 - "GET /api/meetings/3/audio?ticket=eyJabc.def&x=1 HTTP/1.1" 200'
    assert log_redact.redact(line) == '127.0.0.1:5000 - "GET /api/meetings/3/audio?ticket=***&x=1 HTTP/1.1" 200'
    assert log_redact.redact("/api/ws/boards/1?token=eyJ.a.b") == "/api/ws/boards/1?token=***"
    assert log_redact.redact("/api/boards/1") == "/api/boards/1"


def test_filter_installed_on_uvicorn_loggers():
    import app.main  # noqa: F401 — import app là gắn bộ lọc

    # Đúng dạng uvicorn ghi log truy cập: chuỗi mẫu + các tham số
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/api/meetings/1/audio?ticket=bi-mat", "1.1", 200), None,
    )
    for name in ("uvicorn.access", "uvicorn.error"):
        assert logging.getLogger(name).filter(record)
    assert "bi-mat" not in record.getMessage() and "ticket=***" in record.getMessage()
