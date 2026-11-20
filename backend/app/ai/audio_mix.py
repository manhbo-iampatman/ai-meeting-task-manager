"""Xử lý âm thanh cho Online Meeting: đo âm lượng từng câu và trộn các track thành một file.

Chỉ worker AI dùng (cần numpy + PyAV, đã có sẵn vì faster-whisper cần). Mọi hàm đều xử lý
**theo luồng (streaming từng khối 1 giây)** để tốn RAM hằng số (chỉ vài MB ngay cả khi họp
nhiều giờ) thay vì giữ cả buổi họp trong RAM, đồng thời nén biên độ mượt (`soft_limit`) để
không rè tiếng khi nhiều người nói đè nhau. Lỗi thì trả `None / False`: thiếu file trộn hay
thiếu số đo âm lượng không được làm hỏng bản ghi.
"""

from contextlib import ExitStack
import logging
import math
from pathlib import Path
import wave

log = logging.getLogger(__name__)

RATE = 16000  # Hz — cùng tần số Whisper dùng
BLOCK_SAMPLES = RATE  # xử lý từng khối 1 giây (~64 KB float32 mỗi track)


def soft_limit(samples, knee: float = 0.75, ceiling: float = 0.98):
    """Chống rè tiếng (clipping) khi cộng nhiều track lúc mọi người nói đè nhau.

    - Dưới ngưỡng `knee` (0,75): giữ NGUYÊN biên độ (không làm nhỏ tiếng khi 1 người nói).
    - Trên ngưỡng `knee`: nén mượt dạng hữu tỉ `knee + h * e / (e + h)` về dưới `ceiling` (0,98)
      nên ngay cả khi 6 người nói đè nhau vẫn không bị cắt phẳng thành ±1,0.
    """
    import numpy as np

    abs_x = np.abs(samples)
    if not np.any(abs_x > knee):
        return samples
    headroom = ceiling - knee
    excess = np.maximum(abs_x - knee, 0.0)
    limited = knee + headroom * (excess / (excess + headroom))
    return np.where(abs_x > knee, np.sign(samples) * limited, samples)


def _av_errors(av) -> tuple[type[BaseException], ...]:
    """Lớp lỗi giải mã của PyAV. Bản >= 14 đổi `av.AVError` thành `av.FFmpegError` — viết
    `except av.AVError` trên PyAV 15 tự gây `AttributeError` ngay khi có lỗi cần bắt."""
    errs = tuple(e for e in (getattr(av, "FFmpegError", None), getattr(av, "AVError", None)) if e is not None)
    return errs or (OSError,)


def _iter_pcm_blocks(path: Path, block_samples: int = BLOCK_SAMPLES):
    """Giải mã file âm thanh theo từng khối 1D `float32` mono 16 kHz (RAM O(1)).

    Nếu gói cuối bị cụt (đóng tab đột ngột hoặc đoạn `.m4a` bị ngắt giữa chừng), dừng êm
    sau khi đã trả toàn bộ phần âm thanh hợp lệ phía trước.
    """
    import av
    import numpy as np

    av_errors = _av_errors(av)
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            return
        resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
        buf = np.empty(0, dtype=np.float32)

        def push(arr):
            nonlocal buf
            flat = np.asarray(arr, dtype=np.float32).reshape(-1)
            if flat.size == 0:
                return
            buf = flat if buf.size == 0 else np.concatenate([buf, flat])

        try:
            for packet in container.demux(stream):
                if packet.dts is None:
                    continue
                try:
                    for frame in packet.decode():
                        for rf in resampler.resample(frame):
                            push(rf.to_ndarray())
                            while buf.size >= block_samples:
                                yield buf[:block_samples]
                                buf = buf[block_samples:]
                except av_errors as e:
                    log.warning("Gói bị lỗi ở %s (dừng tại đây, giữ phần đã đọc): %s", path, e)
                    break
        except av_errors as e:
            log.warning("File %s bị cụt đuôi (giữ phần đã đọc): %s", path, e)

        try:
            for rf in resampler.resample(None):
                push(rf.to_ndarray())
        except av_errors:
            pass
        while buf.size >= block_samples:
            yield buf[:block_samples]
            buf = buf[block_samples:]
        if buf.size > 0:
            yield buf


def load_audio(path: Path):
    """Giải mã toàn bộ file ghi âm thành mảng số (mono, 16 kHz, −1..1). Lỗi → None."""
    try:
        import numpy as np

        chunks = list(_iter_pcm_blocks(path))
        return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)
    except Exception as e:  # noqa: BLE001 — file hỏng / rỗng
        log.warning("Không giải mã được %s: %s", path, e)
        return None


def segment_rms(audio, start: float, end: float) -> float | None:
    """Âm lượng trung bình (RMS) của đoạn [start, end] giây từ mảng âm thanh đã giải mã."""
    if audio is None:
        return None
    import numpy as np

    a, b = max(0, int(start * RATE)), min(len(audio), int(end * RATE))
    if b <= a:
        return None
    return round(float(np.sqrt(np.mean(np.square(audio[a:b], dtype=np.float64)))), 5)


def segments_rms(path: Path, intervals: list[tuple[float, float]]) -> list[float | None]:
    """Đo RMS của nhiều đoạn `[start, end]` bằng cách đọc file theo luồng (không nạp cả file vào RAM)."""
    if not intervals:
        return []
    import numpy as np

    ranges = [(max(0, int(s * RATE)), max(0, int(e * RATE))) for s, e in intervals]
    sum_sq = [0.0] * len(ranges)
    counts = [0] * len(ranges)
    try:
        cursor = 0
        for block in _iter_pcm_blocks(path):
            b_end = cursor + len(block)
            for idx, (a, b) in enumerate(ranges):
                if b <= cursor or a >= b_end or b <= a:
                    continue
                lo = max(a, cursor) - cursor
                hi = min(b, b_end) - cursor
                if hi > lo:
                    seg = block[lo:hi]
                    sum_sq[idx] += float(np.dot(seg.astype(np.float64), seg.astype(np.float64)))
                    counts[idx] += hi - lo
            cursor = b_end
    except Exception as e:  # noqa: BLE001 — file hỏng / rỗng
        log.warning("Không đo được âm lượng của %s: %s", path, e)
        return [None] * len(ranges)

    return [round(math.sqrt(sum_sq[i] / counts[i]), 5) if counts[i] > 0 else None for i in range(len(ranges))]


def transcode_safe_wav(src: Path, dest: Path) -> bool:
    """Giải mã an toàn từng gói sang `.wav` 16 kHz mono để cứu file bị cụt đuôi hoặc `.m4a` lỗi container."""
    import numpy as np

    tmp = dest.with_name(dest.stem + ".recovering" + dest.suffix)
    wrote = 0
    try:
        with wave.open(str(tmp), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(RATE)
            for block in _iter_pcm_blocks(src):
                pcm = np.round(soft_limit(block) * 32767).astype(np.int16)
                wf.writeframes(pcm.tobytes())
                wrote += len(pcm)
        if wrote == 0:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(dest)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Không cứu được âm thanh từ %s: %s", src, e)
        tmp.unlink(missing_ok=True)
        return False


class _TrackStream:
    """Bộ đọc theo luồng cho một track, giữ đệm nhỏ (~1 giây) và tự đóng file khi xong."""

    def __init__(self, path: Path, offset_sec: float) -> None:
        import numpy as np

        self.path = path
        self.offset_samples = max(0, int(round(offset_sec * RATE)))
        self._gen = _iter_pcm_blocks(path)
        self._buf = np.empty(0, dtype=np.float32)
        self.eof = False

    def prime(self) -> bool:
        """Đọc thử khối đầu tiên: trả False nếu file rỗng hoặc không giải mã được."""
        try:
            first = next(self._gen)
            self._buf = first
            return len(first) > 0
        except StopIteration:
            self.eof = True
            return False
        except Exception as e:  # noqa: BLE001
            log.warning("Bỏ qua track không giải mã được %s: %s", self.path, e)
            self.eof = True
            return False

    def read(self, n: int):
        import numpy as np

        while not self.eof and len(self._buf) < n:
            try:
                nxt = next(self._gen)
                self._buf = nxt if self._buf.size == 0 else np.concatenate([self._buf, nxt])
            except StopIteration:
                self.eof = True
                break
            except Exception as e:  # noqa: BLE001
                log.warning("Dừng đọc sớm track %s: %s", self.path, e)
                self.eof = True
                break
        if self._buf.size == 0:
            return self._buf
        out = self._buf[:n]
        self._buf = self._buf[n:]
        return out

    def close(self) -> None:
        self._gen.close()


def mix_files(sources: list[tuple[Path, float]], dest: Path) -> tuple[bool, float]:
    """Trộn nhiều track theo luồng thành MỘT file `.webm` (Opus 32 kbps) với RAM O(1) và chống rè tiếng.

    Trả về `(thành_công, thời_lượng_giây)`.
    """
    if not sources:
        return False, 0.0
    import av
    import numpy as np

    tmp = dest.with_name(dest.stem + ".mixing" + dest.suffix)
    try:
        with ExitStack() as stack:
            readers: list[_TrackStream] = []
            for path, offset in sources:
                r = _TrackStream(path, offset)
                stack.callback(r.close)
                if r.prime():
                    readers.append(r)
            if not readers:
                return False, 0.0

            total_samples = 0
            with av.open(str(tmp), "w", format="webm") as out:
                stream = out.add_stream("libopus", rate=RATE, layout="mono")
                stream.bit_rate = 32000
                resampler = av.AudioResampler(
                    format=stream.format, layout="mono", rate=RATE, frame_size=stream.frame_size or 960
                )

                cursor = 0
                while True:
                    mix = np.zeros(BLOCK_SAMPLES, dtype=np.float32)
                    block_len = 0
                    any_future = False
                    for r in readers:
                        if r.eof and r._buf.size == 0:
                            continue
                        if cursor + BLOCK_SAMPLES <= r.offset_samples:
                            any_future = True
                            continue
                        lead = max(0, r.offset_samples - cursor)
                        chunk = r.read(BLOCK_SAMPLES - lead)
                        if chunk.size > 0:
                            mix[lead : lead + chunk.size] += chunk
                            block_len = max(block_len, lead + chunk.size)
                        if not r.eof or r._buf.size > 0:
                            any_future = True

                    if block_len == 0 and not any_future:
                        break
                    emit = mix if any_future else mix[:block_len]
                    if emit.size == 0:
                        break
                    pcm = np.round(soft_limit(emit) * 32767).astype(np.int16)
                    frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
                    frame.sample_rate = RATE
                    for f in resampler.resample(frame):
                        out.mux(stream.encode(f))
                    cursor += emit.size
                    total_samples += emit.size

                if total_samples == 0:
                    tmp.unlink(missing_ok=True)
                    return False, 0.0
                for f in resampler.resample(None):
                    out.mux(stream.encode(f))
                out.mux(stream.encode(None))

        tmp.replace(dest)
        return True, round(total_samples / RATE, 2)
    except Exception as e:  # noqa: BLE001
        log.warning("Không ghi được file trộn %s: %s", dest, e)
        tmp.unlink(missing_ok=True)
        return False, 0.0


class Mixer:
    """Trộn các mảng âm thanh trong bộ nhớ (giữ lại cho test / đoạn ngắn; có `soft_limit`)."""

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

        pcm = np.round(soft_limit(self.buf) * 32767).astype(np.int16)
        tmp = dest.with_name(dest.stem + ".mixing" + dest.suffix)
        try:
            with av.open(str(tmp), "w", format="webm") as out:
                stream = out.add_stream("libopus", rate=RATE, layout="mono")
                stream.bit_rate = 32000
                resampler = av.AudioResampler(
                    format=stream.format, layout="mono", rate=RATE, frame_size=stream.frame_size or 960
                )
                for i in range(0, len(pcm), BLOCK_SAMPLES):
                    frame = av.AudioFrame.from_ndarray(pcm[i : i + BLOCK_SAMPLES].reshape(1, -1), format="s16", layout="mono")
                    frame.sample_rate = RATE
                    for f in resampler.resample(frame):
                        out.mux(stream.encode(f))
                for f in resampler.resample(None):
                    out.mux(stream.encode(f))
                out.mux(stream.encode(None))
            tmp.replace(dest)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Không ghi được file trộn %s: %s", dest, e)
            tmp.unlink(missing_ok=True)
            return False
