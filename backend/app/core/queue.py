"""Hàng đợi công việc nền (Redis + RQ).

Luồng: API nhận file -> đưa "job" vào hàng đợi `meetings` -> trả kết quả ngay.
Worker (chạy riêng) lấy job ra xử lý (STT, LLM) và cập nhật trạng thái.
"""

from redis import Redis
from rq import Queue

from app.core.config import get_settings

settings = get_settings()

redis_conn = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)

# Một hàng đợi duy nhất cho xử lý cuộc họp. Worker chạy 1 job mỗi lần
# vì GPU chỉ có 4GB VRAM.
meeting_queue = Queue("meetings", connection=redis_conn, default_timeout=60 * 60)
