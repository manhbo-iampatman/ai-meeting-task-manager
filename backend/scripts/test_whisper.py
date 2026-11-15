"""Chạy thử faster-whisper trên GPU với 1 file ghi âm.

Cách dùng (trong thư mục backend, đã kích hoạt .venv):
    python scripts/test_whisper.py <đường_dẫn_file_audio> [--model large-v3-turbo] [--device cuda] [--lang vi]

Lần chạy đầu sẽ tải mô hình (~1.6GB với large-v3-turbo) vào backend/models_cache/.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # để import được "app"
sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định không in được tiếng Việt

from app.ai.stt.faster_whisper_provider import FasterWhisperProvider  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--lang", default="vi", help="mã ngôn ngữ, hoặc 'auto' để tự nhận")
    args = ap.parse_args()

    print(f"Nạp mô hình {args.model} trên {args.device} ...")
    stt = FasterWhisperProvider(model_size=args.model, device=args.device, download_root="models_cache")

    lang = None if args.lang == "auto" else args.lang
    r = stt.transcribe(args.audio, language=lang, on_progress=lambda p: print(f"\r  tiến độ: {p:5.0%}", end=""))
    print()
    for s in r.segments:
        print(f"[{s.start:7.2f} → {s.end:7.2f}] {s.text}")
    print("-" * 60)
    print(f"Ngôn ngữ: {r.language} | Độ dài audio: {r.duration_sec}s | Thời gian xử lý: {r.processing_sec}s")
    if r.processing_sec:
        print(f"Tốc độ: nhanh gấp {r.duration_sec / r.processing_sec:.1f} lần thời gian thực")


if __name__ == "__main__":
    main()
