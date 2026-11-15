"""STT chạy trên máy bằng faster-whisper (Whisper tối ưu bằng CTranslate2).

Các tham số quan trọng (sẽ giải thích kỹ khi bảo vệ):
- compute_type="int8_float16": lượng tử hóa trọng số về int8 → tốn ít VRAM
  (vừa GPU 4GB) mà độ chính xác giảm không đáng kể.
- vad_filter=True: dùng Silero VAD bỏ các đoạn im lặng → nhanh hơn và giảm
  hiện tượng Whisper "bịa chữ" khi không có tiếng nói.
- beam_size=5: tìm kiếm chùm, cân nhắc 5 khả năng song song khi giải mã.
"""

import time

from app.ai.cuda_setup import setup_cuda_dlls
from app.ai.stt.base import ProgressCallback, Segment, TranscriptResult


class FasterWhisperProvider:
    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        device: str = "cuda",
        compute_type: str = "int8_float16",
        download_root: str | None = None,
    ):
        setup_cuda_dlls()
        from faster_whisper import WhisperModel  # import muộn: chỉ worker AI cần

        if device == "cpu" and "float16" in compute_type:
            compute_type = "int8"  # CPU không hỗ trợ float16
        self.name = f"faster-whisper/{model_size}"
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type, download_root=download_root)

    def transcribe(
        self, audio_path: str, language: str | None = "vi", on_progress: ProgressCallback | None = None
    ) -> TranscriptResult:
        t0 = time.perf_counter()
        segments_iter, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )

        # segments_iter là generator: mô hình chỉ thực sự chạy khi ta duyệt qua
        segments: list[Segment] = []
        for s in segments_iter:
            segments.append(Segment(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip()))
            if on_progress and info.duration:
                on_progress(min(s.end / info.duration, 1.0))

        return TranscriptResult(
            text=" ".join(s.text for s in segments),
            segments=segments,
            language=info.language,
            duration_sec=round(info.duration, 2),
            processing_sec=round(time.perf_counter() - t0, 2),
            model=self.name,
        )
