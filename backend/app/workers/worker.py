"""Khởi động worker xử lý hàng đợi `meetings`.

Chạy (trong thư mục backend, đã kích hoạt .venv):
    python -m app.workers.worker

Vì sao không dùng lệnh `rq worker` mặc định?
- Worker mặc định của RQ dùng os.fork() — Windows KHÔNG có fork.
- SimpleWorker chạy job ngay trong tiến trình hiện tại → dùng được trên
  Windows, và còn có lợi: mô hình Whisper nạp 1 lần, giữ trong VRAM cho
  các job sau (không phải nạp lại mỗi lần, tiết kiệm ~10 giây/job).
- Timeout dùng TimerDeathPenalty (luồng hẹn giờ) thay cho tín hiệu SIGALRM
  vốn không có trên Windows.
- Worker xử lý TUẦN TỰ từng cuộc họp → GPU 4GB không bao giờ bị tràn bộ nhớ.
"""

import logging
import sys

from rq import SimpleWorker
from rq.timeouts import TimerDeathPenalty

from app.core.queue import meeting_queue, redis_conn


class WindowsSimpleWorker(SimpleWorker):
    death_penalty_class = TimerDeathPenalty


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows in được tiếng Việt
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("worker")

    # Nạp sẵn mô hình ngay khi khởi động → job đầu tiên không phải chờ, và lỗi GPU lộ ra sớm
    try:
        from app.ai.stt import get_stt_provider

        log.info("Đang nạp mô hình nhận dạng giọng nói...")
        stt = get_stt_provider()
        log.info("Sẵn sàng: %s", stt.name)
    except Exception:  # noqa: BLE001
        log.exception("Không nạp được mô hình STT — job sẽ thử nạp lại khi chạy")

    worker = WindowsSimpleWorker([meeting_queue], connection=redis_conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
