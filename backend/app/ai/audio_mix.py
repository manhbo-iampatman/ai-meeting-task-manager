"""Xử lý âm thanh cho Online Meeting: đo âm lượng từng câu và trộn các track thành một file.

Chỉ worker AI dùng (cần numpy + PyAV, đã có sẵn vì faster-whisper cần). Mọi hàm đều "lỗi thì
trả None / False": thiếu file trộn hay thiếu số đo âm lượng không được làm hỏng bản ghi.
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)

RATE = 16000  # Hz — cùng tần số Whisper dùng


def load_audio(path: Path):
    """Giải mã file ghi âm thành mảng số (mono, 16 kHz, giá trị −1..1). Lỗi → None."""
    try:
        from faster_whisper.audio import decode_audio

        return decode_audio(str(path), sampling_rate=RATE)
    except Exception as e:  # noqa: BLE001 — file hỏng / rỗng
        log.warning("Không giải mã được %s: %s", path, e)
        return None


def segment_rms(audio, start: float, end: float) -> float | None:
    """Âm lượng trung bình (RMS) của đoạn [start, end] giây. Dùng để phân biệt tiếng nói thật
    (to) với tiếng vọng lọt vào mic của người khác (nhỏ)."""
    if audio is None:
        return None
    import numpy as np

    a, b = max(0, int(start * RATE)), min(len(audio), int(end * RATE))
    if b <= a:
        return None
    return round(float(np.sqrt(np.mean(np.square(audio[a:b], dtype=np.float64)))), 5)


class Mixer:
    """Cộng dồn các track lên một trục thời gian chung để có MỘT file nghe lại cả buổi họp."""

    def __init__(self) -> None:
        self.buf = None

    def add(self, audio, offset_sec: float) -> None:
        if audio is None or len(audio) == 0:
            return
        import numpy as np

        start = max(0, int(offset_sec * RATE))
        need = start + len(audio)
        if self.buf is None:
            self.buf = np.zeros(need, dtype=np.float32)
        elif len(self.buf) < need:
            self.buf = np.concatenate([self.buf, np.zeros(need - len(self.buf), dtype=np.float32)])
        self.buf[start:need] += audio

    @property
    def duration_sec(self) -> float:
        return 0.0 if self.buf is None else len(self.buf) / RATE

    def write(self, dest: Path) -> bool:
        """Ghi file .webm (Opus 32 kbps — 1 giờ họp ≈ 14MB). Trả về True nếu ghi được."""
        if self.buf is None or len(self.buf) == 0:
            return False
        import av
        import numpy as np

        pcm = (np.clip(self.buf, -1.0, 1.0) * 32767).astype(np.int16)
        tmp = dest.with_name(dest.stem + ".mixing" + dest.suffix)
        try:
            with av.open(str(tmp), "w", format="webm") as out:
                stream = out.add_stream("libopus", rate=RATE, layout="mono")
                stream.bit_rate = 32000
                # Bộ mã hóa Opus cần khung đúng cỡ → cho đi qua bộ đệm chia khung
                resampler = av.AudioResampler(format=stream.format, layout="mono", rate=RATE, frame_size=stream.frame_size or 960)
                step = RATE  # đưa vào từng giây một
                for i in range(0, len(pcm), step):
                    frame = av.AudioFrame.from_ndarray(pcm[i : i + step].reshape(1, -1), format="s16", layout="mono")
                    frame.sample_rate = RATE
                    for f in resampler.resample(frame):
                        out.mux(stream.encode(f))
                for f in resampler.resample(None):  # xả phần còn lại trong bộ đệm
                    out.mux(stream.encode(f))
                out.mux(stream.encode(None))
            tmp.replace(dest)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Không ghi được file trộn %s: %s", dest, e)
            tmp.unlink(missing_ok=True)
            return False
