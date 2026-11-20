"""Chặn dò mật khẩu: đăng nhập sai quá nhiều lần thì tạm khóa (quyết định 20/11/2026).

Quy tắc: cùng một cặp (email, địa chỉ IP) sai 5 lần trong 15 phút → chặn 15 phút.
- Đếm theo CẶP email + IP, không đếm theo email: nếu chỉ theo email, kẻ xấu cố tình gõ sai
  5 lần là khóa được tài khoản của người khác. Theo cặp thì chỉ máy của kẻ xấu bị chặn.
- Đang bị chặn thì gõ ĐÚNG mật khẩu cũng bị từ chối, nếu không kẻ dò vẫn biết lúc nào trúng.
- Đăng nhập đúng (khi chưa bị chặn) → xóa bộ đếm.

Bộ đếm giữ trong bộ nhớ của tiến trình backend: đơn giản, không cần thêm dịch vụ. Khởi động lại
backend thì bộ đếm mất, chấp nhận được vì MeetFlow chạy 1 tiến trình backend. Muốn chạy nhiều
tiến trình thì chuyển bộ đếm sang Redis.
"""

import math
import threading
import time
from collections.abc import Callable

MAX_FAILS = 5
WINDOW_SEC = 15 * 60  # khoảng thời gian đếm số lần sai
BLOCK_SEC = 15 * 60  # bị chặn bao lâu


class LoginLimiter:
    def __init__(
        self,
        max_fails: int = MAX_FAILS,
        window_sec: float = WINDOW_SEC,
        block_sec: float = BLOCK_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_fails = max_fails
        self.window_sec = window_sec
        self.block_sec = block_sec
        self.clock = clock
        self._fails: dict[tuple[str, str], list[float]] = {}  # thời điểm các lần sai gần đây
        self._blocked_until: dict[tuple[str, str], float] = {}
        # Route đăng nhập là hàm đồng bộ → FastAPI chạy trên nhiều luồng cùng lúc → cần khóa
        self._lock = threading.Lock()

    @staticmethod
    def _key(email: str, ip: str) -> tuple[str, str]:
        return (email.strip().lower(), ip)

    def retry_after(self, email: str, ip: str) -> int:
        """Còn bị chặn bao nhiêu giây (0 = không bị chặn)."""
        key = self._key(email, ip)
        with self._lock:
            until = self._blocked_until.get(key)
            if until is None:
                return 0
            left = until - self.clock()
            if left <= 0:
                del self._blocked_until[key]
                return 0
            return math.ceil(left)

    def record_failure(self, email: str, ip: str) -> None:
        key = self._key(email, ip)
        now = self.clock()
        with self._lock:
            self._prune(now)
            recent = [t for t in self._fails.get(key, []) if now - t < self.window_sec]
            recent.append(now)
            if len(recent) >= self.max_fails:
                self._blocked_until[key] = now + self.block_sec
                self._fails.pop(key, None)
            else:
                self._fails[key] = recent

    def record_success(self, email: str, ip: str) -> None:
        with self._lock:
            self._fails.pop(self._key(email, ip), None)

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()
            self._blocked_until.clear()

    def _prune(self, now: float) -> None:
        """Dọn các mục đã hết hạn để bộ nhớ không phình mãi."""
        if len(self._fails) + len(self._blocked_until) < 1000:
            return
        self._fails = {k: v for k, v in self._fails.items() if v and now - v[-1] < self.window_sec}
        self._blocked_until = {k: v for k, v in self._blocked_until.items() if v > now}


login_limiter = LoginLimiter()
