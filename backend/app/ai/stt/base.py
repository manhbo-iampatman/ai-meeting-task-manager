"""Giao diện chung (interface) cho mọi bộ chuyển giọng nói thành văn bản (STT).

Mỗi nhà cung cấp (faster-whisper trên máy, Groq API, ...) chỉ cần cài đặt
hàm `transcribe`. Phần còn lại của hệ thống chỉ biết tới `STTProvider`,
nên đổi mô hình = đổi biến môi trường STT_PROVIDER, không phải sửa code.
(Mẫu thiết kế Strategy — có thể nêu trong báo cáo.)
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Segment:
    start: float  # giây bắt đầu
    end: float  # giây kết thúc
    text: str


@dataclass
class TranscriptResult:
    text: str
    segments: list[Segment] = field(default_factory=list)
    language: str = "vi"
    duration_sec: float = 0.0
    processing_sec: float = 0.0
    model: str = ""


# Hàm báo tiến độ: nhận số từ 0.0 tới 1.0
ProgressCallback = Callable[[float], None]


class STTProvider(Protocol):
    name: str

    def transcribe(
        self, audio_path: str, language: str | None = "vi", on_progress: ProgressCallback | None = None
    ) -> TranscriptResult: ...
