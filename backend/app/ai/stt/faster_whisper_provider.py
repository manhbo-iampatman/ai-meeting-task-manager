"""STT chạy trên máy bằng faster-whisper (Whisper tối ưu bằng CTranslate2).

Các tham số quan trọng (sẽ giải thích kỹ khi bảo vệ):
- compute_type="int8_float16": lượng tử hóa trọng số về int8 → tốn ít VRAM
  (vừa GPU 4GB) mà độ chính xác giảm không đáng kể.
- vad_filter=True: dùng Silero VAD bỏ các đoạn im lặng → nhanh hơn và giảm
  hiện tượng Whisper "bịa chữ" khi không có tiếng nói.
- beam_size=5: tìm kiếm chùm, cân nhắc 5 khả năng song song khi giải mã.
"""

import re
import time
import unicodedata

from app.ai.cuda_setup import setup_cuda_dlls
from app.ai.stt.base import ProgressCallback, Segment, TranscriptResult

SENTENCE_END = (".", "?", "!", "…")

# "Ảo giác" (hallucination) của Whisper: khi gặp im lặng / tiếng ồn, mô hình hay TỰ BỊA
# ra câu chào cuối video YouTube (vì dữ liệu huấn luyện có rất nhiều video kiểu này).
# Danh sách các mẫu hay gặp với tiếng Việt (so khớp không dấu, không phân biệt hoa thường).
HALLUCINATION_PATTERNS = [
    r"subscribe",
    r"dang ky kenh",
    r"like (va|and) share",
    r"khong bo lo nhung video",
    r"cam on cac ban da (theo doi|xem|lang nghe)",
    r"hen gap lai (cac ban )?trong (nhung|cac) video",
    r"la la school",
    r"ghien mi go",
    r"phu de (boi|duoc thuc hien)",
    r"amara\.org",
]
_HALLU_RE = re.compile("|".join(HALLUCINATION_PATTERNS))


def _fold(text: str) -> str:
    """Bỏ dấu tiếng Việt + chữ thường: "Đăng Ký Kênh" → "dang ky kenh"."""
    t = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def is_hallucination(seg) -> bool:
    """Đoạn có phải do Whisper bịa ra không?

    1) Mô hình vừa cho rằng "nhiều khả năng không có tiếng nói" (no_speech_prob cao)
       vừa không tự tin vào chữ sinh ra (avg_logprob thấp) → bỏ.
    2) Khớp mẫu câu ảo giác đã biết → bỏ.
    """
    no_speech = getattr(seg, "no_speech_prob", 0.0) or 0.0
    logprob = getattr(seg, "avg_logprob", 0.0) or 0.0
    if no_speech > 0.6 and logprob < -0.8:
        return True
    return is_hallucination_text(seg.text)


def is_hallucination_text(text: str) -> bool:
    return bool(_HALLU_RE.search(_fold(text)))


def is_prompt_echo(text: str, prompt: str | None) -> bool:
    """Whisper có đang CHÉP LẠI câu gợi ý không?

    Gợi ý (initial_prompt) chứa tên thành viên. Gặp đoạn ghi âm ngắn / không rõ, Whisper
    đôi khi không nghe được gì nên viết ra luôn chữ trong gợi ý (VD: "Nguyễn Văn Nam").
    Dấu hiệu: câu chỉ gồm TOÀN những từ có trong gợi ý.
    """
    if not prompt:
        return False
    words = re.findall(r"\w+", _fold(text))
    prompt_words = set(re.findall(r"\w+", _fold(prompt)))
    return bool(words) and all(w in prompt_words for w in words)


MIN_WORDS = 3  # câu quá ngắn ("Dạ.", "Vâng ạ.") thì gộp với câu sau
MAX_WORDS = 60  # câu quá dài (nói liền không dấu chấm) thì cắt bớt cho dễ đọc


def split_sentences(seg) -> list[Segment]:
    """Whisper trả về các "đoạn" dài tới 30 giây, có khi gồm nhiều câu.

    Dựa vào mốc thời gian từng từ (word timestamps), tách thành từng CÂU có mốc
    riêng → giao diện bấm vào câu nào thì tua audio tới đúng câu đó, và ở Giai đoạn 4
    AI trích dẫn được chính xác câu gốc làm bằng chứng cho mỗi đầu việc.
    """
    words = getattr(seg, "words", None)
    if not words:
        return [Segment(start=round(seg.start, 2), end=round(seg.end, 2), text=seg.text.strip())]

    out: list[Segment] = []
    buf: list = []

    def flush() -> None:
        text = "".join(w.word for w in buf).strip()
        if text:
            out.append(Segment(start=round(buf[0].start, 2), end=round(buf[-1].end, 2), text=text))
        buf.clear()

    for w in words:
        buf.append(w)
        ends = w.word.strip().endswith(SENTENCE_END)
        if (ends and len(buf) >= MIN_WORDS) or len(buf) >= MAX_WORDS:
            flush()
    if buf:
        if out and len(buf) < MIN_WORDS:  # phần đuôi quá ngắn → nối vào câu trước
            last = out.pop()
            buf_text = "".join(w.word for w in buf).strip()
            out.append(Segment(start=last.start, end=round(buf[-1].end, 2), text=f"{last.text} {buf_text}"))
        else:
            flush()
    return out


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
        self,
        audio_path: str,
        language: str | None = "vi",
        on_progress: ProgressCallback | None = None,
        initial_prompt: str | None = None,
    ) -> TranscriptResult:
        t0 = time.perf_counter()
        self.dropped: list[str] = []  # các câu bị lọc vì nghi ảo giác (ghi log để báo cáo)
        self.prompt_echo = False
        segments, info = self._run(audio_path, language, on_progress, initial_prompt)

        # Phát hiện Whisper chép lại gợi ý → chạy lại KHÔNG dùng gợi ý, lấy kết quả đó
        if initial_prompt and any(is_prompt_echo(s.text, initial_prompt) for s in segments):
            self.prompt_echo = True
            self.dropped += [s.text for s in segments if is_prompt_echo(s.text, initial_prompt)]
            segments, info = self._run(audio_path, language, on_progress, None)

        return TranscriptResult(
            text=" ".join(s.text for s in segments),
            segments=segments,
            language=info.language,
            duration_sec=round(info.duration, 2),
            processing_sec=round(time.perf_counter() - t0, 2),
            model=self.name,
        )

    def _run(self, audio_path, language, on_progress, initial_prompt):
        segments_iter, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            # Gợi ý ngữ cảnh: danh sách tên thành viên → Whisper "ưu tiên" viết đúng các tên này
            initial_prompt=initial_prompt,
            # Không dựa vào câu trước khi giải mã câu sau → tránh lỗi lặp câu vô tận ở file dài
            condition_on_previous_text=False,
            # Lấy mốc thời gian của TỪNG TỪ → tách được đoạn theo câu (xem split_sentences)
            word_timestamps=True,
            # Gặp khoảng lặng > 2 giây mà nghi là ảo giác → bỏ qua khoảng lặng đó
            hallucination_silence_threshold=2.0,
        )

        # segments_iter là generator: mô hình chỉ thực sự chạy khi ta duyệt qua
        segments: list[Segment] = []
        for s in segments_iter:
            no_speech = getattr(s, "no_speech_prob", 0.0) or 0.0
            logprob = getattr(s, "avg_logprob", 0.0) or 0.0
            if no_speech > 0.6 and logprob < -0.8:  # cả đoạn nghi không có tiếng nói
                self.dropped.append(s.text.strip())
            else:
                # Lọc ảo giác theo TỪNG CÂU: 1 đoạn có thể vừa có câu thật vừa có câu bịa
                for sent in split_sentences(s):
                    if is_hallucination_text(sent.text):
                        self.dropped.append(sent.text)
                    else:
                        segments.append(sent)
            if on_progress and info.duration:
                on_progress(min(s.end / info.duration, 1.0))
        return segments, info
