"""Chọn bộ STT theo cấu hình. Mô hình được nạp 1 lần rồi giữ lại trong RAM/VRAM."""

from app.ai.stt.base import STTProvider
from app.core.config import get_settings

_provider: STTProvider | None = None


def get_stt_provider() -> STTProvider:
    global _provider
    if _provider is None:
        s = get_settings()
        if s.STT_PROVIDER == "local":
            from app.ai.stt.faster_whisper_provider import FasterWhisperProvider

            _provider = FasterWhisperProvider(
                model_size=s.WHISPER_MODEL,
                device=s.WHISPER_DEVICE,
                compute_type=s.WHISPER_COMPUTE_TYPE,
                download_root=s.WHISPER_MODEL_DIR,
            )
        else:
            raise NotImplementedError("Groq STT sẽ cài đặt ở Giai đoạn 7")
    return _provider
