"""Sinh file ghi âm cuộc họp TIẾNG VIỆT giả lập + đáp án chuẩn (ground truth).

Dùng để:
  1. Chạy thử trọn luồng tải ghi âm → chuyển giọng nói (Giai đoạn 3).
  2. Làm dữ liệu cho chương thực nghiệm (Giai đoạn 6): vì biết trước chính xác
     ai nói gì, ai được giao việc gì → đo được WER và độ chính xác trích xuất.

Giọng đọc: edge-tts (dịch vụ đọc của Microsoft Edge, có 2 giọng tiếng Việt).
Người thứ 3 dùng lại giọng nam nhưng đổi cao độ / tốc độ để nghe khác đi.

Cài:   pip install -r experiments/requirements.txt   (trong .venv của backend)
Chạy:  backend\\.venv\\Scripts\\python experiments\\make_sample_meeting.py
Kết quả trong experiments/data/sample_meeting_01/:
  meeting.wav          — file ghi âm (16kHz mono)
  reference.txt        — bản ghi chuẩn (để tính WER)
  expected_tasks.json  — danh sách đầu việc chuẩn (để chấm bước trích xuất ở GĐ4)
"""

import asyncio
import json
import sys
import wave
from pathlib import Path

import edge_tts
import numpy as np
from faster_whisper.audio import decode_audio

sys.stdout.reconfigure(encoding="utf-8")

SR = 16000
OUT = Path(__file__).parent / "data" / "sample_meeting_01"

# Giọng của từng người: (voice, rate, pitch)
VOICES = {
    "Nam": ("vi-VN-NamMinhNeural", "+0%", "+0Hz"),
    "Lan": ("vi-VN-HoaiMyNeural", "+0%", "+0Hz"),
    "Minh": ("vi-VN-NamMinhNeural", "+12%", "-12Hz"),
}

# Ngày họp giả định: thứ Hai 16/11/2026
MEETING_DATE = "2026-11-16"

SCRIPT: list[tuple[str, str]] = [
    ("Nam", "Chào mọi người, mình bắt đầu buổi họp tuần của nhóm khóa luận nhé."),
    ("Nam", "Tuần trước chúng ta đã xong phần bảng công việc kéo thả rồi. Tuần này tập trung vào phần nhận dạng giọng nói."),
    ("Lan", "Dạ, em đã đọc tài liệu về Whisper. Em thấy bản large v3 turbo chạy khá nhanh trên máy có card đồ họa."),
    ("Nam", "Tốt. Vậy Lan viết chương hai, phần cơ sở lý thuyết về nhận dạng giọng nói, nộp trước thứ Sáu tuần này nhé."),
    ("Lan", "Vâng, thứ Sáu em gửi bản nháp cho anh."),
    ("Nam", "Minh thì sao, phần giao diện trang cuộc họp đến đâu rồi?"),
    ("Minh", "Em làm xong phần tải file lên rồi anh. Còn trình phát âm thanh đồng bộ với bản ghi thì em đang làm."),
    ("Nam", "Ừ, Minh hoàn thành trình phát âm thanh và sửa lỗi hiển thị trên điện thoại, hạn là ngày hai mươi lăm tháng mười một."),
    ("Minh", "Dạ được ạ."),
    ("Nam", "Còn phần anh, anh sẽ chuẩn bị bộ dữ liệu thử nghiệm gồm mười đoạn ghi âm, xong trước thứ Tư tuần sau."),
    ("Lan", "Anh ơi, mình có cần mời thầy hướng dẫn xem bản demo không ạ?"),
    ("Nam", "Có. Lan gửi email hẹn lịch với thầy hướng dẫn giúp anh, trong ngày mai luôn nhé."),
    ("Lan", "Vâng ạ."),
    ("Nam", "Ok, vậy chốt lại: Lan viết chương hai và gửi email cho thầy, Minh làm trình phát âm thanh, anh làm bộ dữ liệu. Cảm ơn mọi người."),
]

# Đáp án chuẩn cho bước trích xuất đầu việc (Giai đoạn 4)
EXPECTED_TASKS = [
    {"assignee": "Lan", "task": "Viết chương 2 – cơ sở lý thuyết về nhận dạng giọng nói", "due_date": "2026-11-20"},
    {"assignee": "Minh", "task": "Hoàn thành trình phát âm thanh và sửa lỗi hiển thị trên điện thoại", "due_date": "2026-11-25"},
    {"assignee": "Nam", "task": "Chuẩn bị bộ dữ liệu thử nghiệm gồm 10 đoạn ghi âm", "due_date": "2026-11-25"},
    {"assignee": "Lan", "task": "Gửi email hẹn lịch demo với thầy hướng dẫn", "due_date": "2026-11-17"},
]


async def synth(text: str, voice: str, rate: str, pitch: str, path: Path) -> None:
    """Dịch vụ miễn phí này chập chờn (~một nửa số lần gọi không trả về âm thanh,
    kể cả cùng 1 câu) → thử lại tối đa 10 lần; từ lần thứ 6 bỏ chỉnh cao độ."""
    for attempt in range(10):
        p = pitch if attempt < 5 else "+0Hz"
        try:
            await edge_tts.Communicate(text, voice, rate=rate, pitch=p).save(str(path))
            return
        except Exception as e:  # noqa: BLE001 — NoAudioReceived, lỗi mạng, hết thời gian kết nối...
            path.unlink(missing_ok=True)
            print(f"      thử lại ({attempt + 1}/10): {type(e).__name__}")
            await asyncio.sleep(1.0 + 0.5 * attempt)
    raise RuntimeError(f"Không sinh được giọng đọc cho: {text[:40]}")


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pieces: list[np.ndarray] = []
    gap = np.zeros(int(SR * 0.6), dtype=np.float32)  # 0,6 giây lặng giữa các câu
    # Lưu từng câu đã tạo xong → chạy lại sẽ tiếp tục từ chỗ dừng (dịch vụ hay lỗi giữa chừng)
    cache = OUT / "_tts_cache"
    cache.mkdir(exist_ok=True)
    for i, (speaker, text) in enumerate(SCRIPT):
        voice, rate, pitch = VOICES[speaker]
        mp3 = cache / f"{i:02d}_{speaker}.mp3"
        if not mp3.exists() or mp3.stat().st_size == 0:
            await synth(text, voice, rate, pitch, mp3)
        pieces += [decode_audio(str(mp3), sampling_rate=SR), gap]
        print(f"  [{i + 1:2d}/{len(SCRIPT)}] {speaker}: {text[:60]}")

    audio = np.concatenate(pieces)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(OUT / "meeting.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())

    (OUT / "reference.txt").write_text("\n".join(t for _, t in SCRIPT) + "\n", encoding="utf-8")
    (OUT / "reference_speakers.txt").write_text("\n".join(f"{s}: {t}" for s, t in SCRIPT) + "\n", encoding="utf-8")
    (OUT / "expected_tasks.json").write_text(
        json.dumps({"meeting_date": MEETING_DATE, "tasks": EXPECTED_TASKS}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Xong: {OUT / 'meeting.wav'}  ({len(audio) / SR:.1f} giây)")


if __name__ == "__main__":
    asyncio.run(main())
