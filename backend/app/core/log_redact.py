"""Che token / vé trong log của uvicorn (lớp phòng hờ, quyết định 20/11/2026).

uvicorn ghi đường link của mỗi request vào log, kể cả phần sau dấu "?". Nếu link có
`token=...` hoặc `ticket=...` thì ai đọc được file log là có token. Bộ lọc này thay giá trị
đó bằng *** trước khi dòng log được in ra.

Từ 20/11/2026 token đăng nhập không còn nằm trên link nữa (realtime gửi token trong tin nhắn
đầu tiên; nghe ghi âm dùng vé riêng), nhưng vẫn giữ bộ lọc để không bao giờ lọt.
"""

import logging
import re

_SECRET_IN_URL = re.compile(r"\b(token|ticket)=[^&\s\"']+", re.IGNORECASE)


def redact(text: str) -> str:
    return _SECRET_IN_URL.sub(r"\1=***", text)


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True  # không bỏ dòng log nào, chỉ che bớt


def install() -> None:
    """Gắn bộ lọc vào 2 logger của uvicorn: "access" (mỗi request HTTP) và "error"
    (uvicorn ghi cả link WebSocket vào đây)."""
    f = RedactSecretsFilter()
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(x, RedactSecretsFilter) for x in logger.filters):
            logger.addFilter(f)
