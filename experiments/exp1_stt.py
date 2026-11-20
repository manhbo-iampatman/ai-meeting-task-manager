"""THÍ NGHIỆM 1 (Giai đoạn 7) — So sánh các mô hình STT tiếng Việt + tác động của `initial_prompt`.

Đo trên 1 cuộc họp hoặc toàn bộ bộ dữ liệu `experiments/data/`:
  - WER thô, WER chuẩn hóa số (Micro & Macro), CER chuẩn hóa
  - Tỉ lệ nhận đúng tên thành viên (đo trực tiếp hiệu quả của `initial_prompt`)
  - Tốc độ xử lý (giây / 1 phút audio, RTF, hệ số × thời gian thực)
  - VRAM TĂNG THÊM so với nền lúc bắt đầu (`nvidia-smi` đo toàn GPU nên chỉ báo phần chênh lệch;
    nên tắt Ollama/ứng dụng nặng khi đo)
  - Số câu ảo giác bị lọc (`dropped`) và số cuộc họp Whisper chép lại gợi ý (`prompt_echo` → MeetFlow
    tự chạy lại KHÔNG gợi ý, nên dòng "có gợi ý" của cuộc đó thực chất là kết quả không gợi ý)

LƯU Ý khi đọc ablation `initial_prompt`: MeetFlow chạy faster-whisper với
`condition_on_previous_text=False`, nên gợi ý tên chỉ tác động lên CỬA SỔ 30 GIÂY ĐẦU TIÊN của file
(faster-whisper 1.2.1, `transcribe.py`: `prompt_reset_since` được đặt lại sau cửa sổ đầu). Với cuộc
họp 3–15 phút, tác động đo được bị pha loãng một cách cấu trúc. Backend `hf:` (transformers) lại đưa
`prompt_ids` vào MỌI đoạn 30 giây → cách áp dụng gợi ý KHÁC nhau giữa 2 backend.
Backend `hf:` cũng KHÔNG có VAD + lọc ảo giác + tách câu như MeetFlow → để so sánh công bằng, ưu tiên
chạy PhoWhisper bản CTranslate2 qua `fw:<repo_ct2>` (cùng pipeline).

Tự động lưu bản ghi STT sinh ra vào `experiments/results/stt_transcripts/<model>/<meeting>.txt` + `.json`
để dùng trực tiếp làm đầu vào cho Thí nghiệm 3 (End-to-End).

Hỗ trợ 2 backend mô hình (truyền trong `--models`):
  - `small`, `medium`, `large-v3-turbo` hoặc `fw:<repo_hoặc_thư_mục_ct2>`:
      Chạy bằng `faster-whisper` (CTranslate2, int8_float16 trên GPU).
      VD: `fw:kiendt/PhoWhisper-large-ct2` hoặc thư mục PhoWhisper đã chuyển sang CTranslate2.
  - `hf:vinai/PhoWhisper-small`, `hf:vinai/PhoWhisper-medium`:
      Chạy trực tiếp mô hình HuggingFace `transformers` (cần `transformers` + torch BẢN CUDA; xem README).
      Với `--device cuda/auto` mà torch không thấy GPU → mô hình đó báo lỗi và bị bỏ qua (không âm thầm
      chạy CPU làm sai số liệu tốc độ).

Mỗi mô hình chạy trong try/except riêng; báo cáo được ghi lại SAU MỖI mô hình, nên 1 mô hình lỗi
(thiếu thư viện, hết VRAM) không làm mất kết quả các mô hình đã chạy xong.

Ví dụ chạy (PowerShell, 1 dòng):
  backend\\.venv\\Scripts\\python experiments\\exp1_stt.py --data experiments/data --models small medium large-v3-turbo --ablate-prompt
  backend\\.venv\\Scripts\\python experiments\\exp1_stt.py --data experiments/data --models large-v3-turbo hf:vinai/PhoWhisper-small hf:vinai/PhoWhisper-medium
"""

from __future__ import annotations

import argparse
import gc
from pathlib import Path
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_DATA_DIR,
    DEFAULT_RESULTS_DIR,
    MeetingCase,
    VRAMMonitor,
    build_stt_prompt,
    compute_wer_metrics,
    discover_meetings,
    fmt_pct,
    load_backend_settings,
    markdown_table,
    read_text,
    select_cases,
    slugify_model,
    warn_roster,
    write_csv,
    write_json,
    write_markdown,
)


def parse_model_spec(spec: str) -> tuple[str, str]:
    """`small` → ('fw', 'small'); `hf:vinai/PhoWhisper-small` → ('hf', 'vinai/PhoWhisper-small')."""
    if ":" in spec:
        backend, rest = spec.split(":", 1)
        if backend in ("fw", "faster-whisper"):
            return "fw", rest
        if backend in ("hf", "transformers"):
            return "hf", rest
    return "fw", spec


class _HFWhisperRunner:
    """Chạy PhoWhisper / Whisper gốc từ HuggingFace `transformers` (tùy chọn cho TN1)."""

    def __init__(self, model_id: str, device: str = "cuda", cache_dir: str | None = None) -> None:
        try:
            import torch
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
        except ImportError as e:
            raise RuntimeError(
                f"Để chạy `{model_id}` qua backend `hf:`, cần cài thêm torch BẢN CUDA rồi transformers: "
                "backend\\.venv\\Scripts\\pip install torch --index-url https://download.pytorch.org/whl/cu124 ; "
                "backend\\.venv\\Scripts\\pip install transformers "
                "(pip install torch thường = bản CPU-only trên Windows). "
                "Hoặc dùng bản CTranslate2 qua `fw:<repo_ct2>` để chạy cùng pipeline faster-whisper."
            ) from e

        if device in ("cuda", "auto") and not torch.cuda.is_available():
            raise RuntimeError(
                "!!! torch KHÔNG thấy GPU CUDA (thường do pip cài bản torch CPU-only) → PhoWhisper sẽ chạy CPU, "
                "số liệu tốc độ/VRAM không so được với faster-whisper. Cài torch bản CUDA, VD: "
                "backend\\.venv\\Scripts\\pip install torch --index-url https://download.pytorch.org/whl/cu124 "
                "— hoặc chạy cố ý trên CPU bằng --device cpu."
            )
        if device == "cpu":
            print("!!! CẢNH BÁO: backend hf: đang chạy trên CPU — tốc độ KHÔNG so sánh được với faster-whisper trên GPU.")
        use_cuda = device in ("cuda", "auto")
        self.device = "cuda" if use_cuda else "cpu"
        dtype = torch.float16 if use_cuda else torch.float32
        self._torch = torch
        self.name = f"hf/{model_id}"
        self.model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_id, torch_dtype=dtype, low_cpu_mem_usage=True, cache_dir=cache_dir
        )
        if use_cuda:
            self.model.to("cuda")
        self.processor = AutoProcessor.from_pretrained(model_id, cache_dir=cache_dir)
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=self.model,
            tokenizer=self.processor.tokenizer,
            feature_extractor=self.processor.feature_extractor,
            torch_dtype=dtype,
            device=0 if use_cuda else -1,
            chunk_length_s=30,
            stride_length_s=5,
        )
        self.dropped: list[str] = []
        self.prompt_echo = False
        self.pipeline_note = "transformers pipeline (không VAD, không lọc ảo giác, prompt_ids cho mọi đoạn 30s)"

    def warmup(self) -> None:
        """Làm nóng GPU trên 1 giây im lặng để lần đo đầu không chậm giả tạo (công bằng với faster-whisper)."""
        import numpy as np

        try:
            self.pipe(np.zeros(16000, dtype=np.float32), generate_kwargs={"language": "vi", "task": "transcribe"})
        except Exception:  # noqa: BLE001
            pass

    def transcribe(self, audio_path: str, language: str = "vi", initial_prompt: str | None = None) -> dict[str, Any]:
        from faster_whisper.audio import decode_audio

        t0 = time.perf_counter()
        audio = decode_audio(audio_path, sampling_rate=16000)
        duration = round(len(audio) / 16000.0, 2)
        gen_kwargs: dict[str, Any] = {"language": language, "task": "transcribe"}
        if initial_prompt:
            prompt_ids = self.processor.get_prompt_ids(initial_prompt, return_tensors="pt")
            if self._torch.cuda.is_available() and next(self.model.parameters()).is_cuda:
                prompt_ids = prompt_ids.to("cuda")
            gen_kwargs["prompt_ids"] = prompt_ids
        out = self.pipe(audio, return_timestamps=True, generate_kwargs=gen_kwargs)
        took = round(time.perf_counter() - t0, 2)
        text = str(out.get("text", "")).strip()
        chunks = out.get("chunks") or []
        segments = []
        for ch in chunks:
            ts = ch.get("timestamp") or (0.0, duration)
            st, en = float(ts[0] or 0.0), float(ts[1] or duration)
            txt = str(ch.get("text", "")).strip()
            if txt:
                segments.append({"start": round(st, 2), "end": round(en, 2), "text": txt})
        if not segments and text:
            segments = [{"start": 0.0, "end": duration, "text": text}]
        return {
            "text": text,
            "segments": segments,
            "duration_sec": duration,
            "processing_sec": took,
            "dropped": [],
            "prompt_echo": False,
        }

    def close(self) -> None:
        del self.pipe, self.model, self.processor
        gc.collect()
        if self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()


class _FasterWhisperRunner:
    """Chạy đúng `FasterWhisperProvider` của MeetFlow (giữ nguyên VAD + lọc ảo giác + tách câu)."""

    def __init__(self, model_id: str, device: str, compute_type: str, download_root: str) -> None:
        from app.ai.stt.faster_whisper_provider import FasterWhisperProvider

        self.provider = FasterWhisperProvider(
            model_size=model_id, device=device, compute_type=compute_type, download_root=download_root
        )
        self.name = self.provider.name
        self.device = device
        self.pipeline_note = "MeetFlow FasterWhisperProvider (VAD + lọc ảo giác + tách câu)"

    def warmup(self) -> None:
        """Làm nóng CUDA/cuDNN trên 0,5 giây im lặng để lần đo đầu tiên không bị chậm giả tạo."""
        import numpy as np

        try:
            list(self.provider.model.transcribe(np.zeros(8000, dtype=np.float32), language="vi")[0])
        except Exception:  # noqa: BLE001
            pass

    def transcribe(self, audio_path: str, language: str = "vi", initial_prompt: str | None = None) -> dict[str, Any]:
        res = self.provider.transcribe(audio_path, language=language, initial_prompt=initial_prompt)
        return {
            "text": res.text,
            "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in res.segments],
            "duration_sec": res.duration_sec,
            "processing_sec": res.processing_sec,
            "dropped": list(getattr(self.provider, "dropped", [])),
            "prompt_echo": bool(getattr(self.provider, "prompt_echo", False)),
        }

    def close(self) -> None:
        del self.provider
        gc.collect()


def aggregate_stt_runs(model_label: str, use_prompt: bool, rows: list[dict[str, Any]], vram: dict[str, int | None]) -> dict[str, Any]:
    """Tổng hợp Micro / Macro WER, tốc độ và VRAM cho 1 cấu hình mô hình trên toàn bộ dataset."""
    total_raw_err = sum(r["wer"]["raw_errors"] for r in rows)
    total_raw_ref = sum(r["wer"]["raw_ref_words"] for r in rows)
    total_norm_err = sum(r["wer"]["substitutions"] + r["wer"]["deletions"] + r["wer"]["insertions"] for r in rows)
    total_norm_ref = sum(r["wer"]["ref_words"] for r in rows)
    total_name_hits = sum(r["wer"]["name_hits"] for r in rows)
    total_name_total = sum(r["wer"]["name_total"] for r in rows)
    total_dur = sum(r["duration_sec"] for r in rows)
    total_proc = sum(r["processing_sec"] for r in rows)
    n = len(rows)

    micro_wer_raw = total_raw_err / total_raw_ref if total_raw_ref else 0.0
    micro_wer_norm = total_norm_err / total_norm_ref if total_norm_ref else 0.0
    macro_wer_raw = sum(r["wer"]["wer_raw"] for r in rows) / n if n else 0.0
    macro_wer_norm = sum(r["wer"]["wer_norm"] for r in rows) / n if n else 0.0
    macro_cer_norm = sum(r["wer"]["cer_norm"] for r in rows) / n if n else 0.0
    name_acc = total_name_hits / total_name_total if total_name_total else None
    sec_per_min = (total_proc / total_dur * 60.0) if total_dur else 0.0
    rtf = (total_proc / total_dur) if total_dur else 0.0
    speedup = (total_dur / total_proc) if total_proc else 0.0

    return {
        "model": model_label,
        "use_prompt": use_prompt,
        "meetings_count": n,
        "micro_wer_raw": round(micro_wer_raw, 4),
        "micro_wer_norm": round(micro_wer_norm, 4),
        "macro_wer_raw": round(macro_wer_raw, 4),
        "macro_wer_norm": round(macro_wer_norm, 4),
        "macro_cer_norm": round(macro_cer_norm, 4),
        "name_hits": total_name_hits,
        "name_total": total_name_total,
        "name_accuracy": round(name_acc, 4) if name_acc is not None else None,
        "total_duration_sec": round(total_dur, 2),
        "total_processing_sec": round(total_proc, 2),
        "sec_per_audio_min": round(sec_per_min, 2),
        "rtf": round(rtf, 4),
        "realtime_factor_x": round(speedup, 2),
        "baseline_vram_mb": vram.get("baseline_mb"),
        "peak_vram_mb": vram.get("peak_mb"),
        "delta_vram_mb": vram.get("delta_mb"),
        "dropped_total": sum(r["dropped_count"] for r in rows),
        "prompt_echo_count": sum(1 for r in rows if r["prompt_echo"]),
        "per_meeting": rows,
    }


def evaluate_model_config(
    spec: str,
    cases: list[MeetingCase],
    prompt_modes: list[bool],
    device: str,
    compute_type: str,
    model_dir: str,
    transcripts_root: Path,
) -> list[dict[str, Any]]:
    backend, model_id = parse_model_spec(spec)
    print(f"\n=== Nạp mô hình STT: {spec} (device={device}, compute_type={compute_type}) ===")
    results: list[dict[str, Any]] = []

    with VRAMMonitor() as vm:
        t_load = time.perf_counter()
        if backend == "fw":
            runner: Any = _FasterWhisperRunner(model_id, device, compute_type, model_dir)
        else:
            runner = _HFWhisperRunner(model_id, device, cache_dir=model_dir)
        runner.warmup()
        load_sec = round(time.perf_counter() - t_load, 2)
        print(f"  Đã nạp `{runner.name}` trong {load_sec}s (VRAM tăng thêm: {vm.delta_mb if vm.delta_mb is not None else '—'} MB)")

        try:
            for use_prompt in prompt_modes:
                tag = "prompt" if use_prompt else "noprompt"
                save_dir = transcripts_root / f"{slugify_model(runner.name)}__{tag}"
                save_dir.mkdir(parents=True, exist_ok=True)
                rows: list[dict[str, Any]] = []

                print(f"\n  -- Cấu hình: {runner.name} | initial_prompt={'CÓ' if use_prompt else 'KHÔNG'} --")
                for c in cases:
                    assert c.audio_path is not None and c.reference_path is not None
                    ref_text = read_text(c.reference_path)
                    prompt = build_stt_prompt(c.members) if use_prompt else None
                    out = runner.transcribe(str(c.audio_path), language="vi", initial_prompt=prompt)
                    wer = compute_wer_metrics(ref_text, out["text"], members=c.members)

                    # Lưu bản ghi để dùng trực tiếp cho TN3 (End-to-End) và phân tích lỗi
                    (save_dir / f"{c.meeting_id}.txt").write_text(
                        "\n".join(s["text"] for s in out["segments"]) + "\n", encoding="utf-8"
                    )
                    write_json(
                        save_dir / f"{c.meeting_id}.json",
                        {
                            "meeting_id": c.meeting_id,
                            "model": runner.name,
                            "use_prompt": use_prompt,
                            "duration_sec": out["duration_sec"],
                            "processing_sec": out["processing_sec"],
                            "segments": out["segments"],
                        },
                    )
                    row = {
                        "meeting_id": c.meeting_id,
                        "duration_sec": out["duration_sec"],
                        "processing_sec": out["processing_sec"],
                        "dropped_count": len(out["dropped"]),
                        "dropped_samples": out["dropped"][:5],
                        "prompt_echo": out["prompt_echo"],
                        "transcript_dir": str(save_dir),
                        "wer": wer.to_dict(),
                    }
                    rows.append(row)
                    name_str = f" | tên {wer.name_hits}/{wer.name_total}" if wer.name_total else ""
                    print(
                        f"    [{c.meeting_id}] {out['duration_sec']:.1f}s → {out['processing_sec']:.1f}s | "
                        f"WER thô {fmt_pct(wer.wer_raw, 2)} | WER số {fmt_pct(wer.wer_norm, 2)} | "
                        f"CER {fmt_pct(wer.cer_norm, 2)}{name_str}"
                    )

                vram_snapshot = {"baseline_mb": vm.baseline_mb, "peak_mb": vm.peak_mb, "delta_mb": vm.delta_mb}
                summary = aggregate_stt_runs(runner.name, use_prompt, rows, vram_snapshot)
                summary["load_sec"] = load_sec
                summary["transcript_dir"] = str(save_dir)
                summary["device"] = getattr(runner, "device", device)
                summary["pipeline"] = getattr(runner, "pipeline_note", "")
                results.append(summary)
        finally:
            runner.close()
            time.sleep(0.5)  # nhường CUDA giải phóng bộ nhớ trước khi nạp mô hình kế tiếp

    return results


def export_exp1_reports(summaries: list[dict[str, Any]], out_dir: Path, failed: list[dict[str, Any]] | None = None) -> None:
    write_json(out_dir / "exp1_stt.json", {"experiment": "exp1_stt", "runs": summaries, "failed_models": failed or []})

    headers = [
        "Mô hình",
        "Gợi ý tên",
        "Số cuộc họp",
        "WER thô (Micro)",
        "WER chuẩn hóa (Micro)",
        "WER chuẩn hóa (Macro)",
        "CER",
        "Đúng tên thành viên",
        "Giây / 1 phút audio",
        "Nhanh hơn RT",
        "VRAM tăng thêm (MB)",
        "Chép lại gợi ý (cuộc)",
        "Thiết bị",
    ]
    rows = [
        [
            r["model"],
            "Có" if r["use_prompt"] else "Không",
            r["meetings_count"],
            fmt_pct(r["micro_wer_raw"], 2),
            fmt_pct(r["micro_wer_norm"], 2),
            fmt_pct(r["macro_wer_norm"], 2),
            fmt_pct(r["macro_cer_norm"], 2),
            f"{r['name_hits']}/{r['name_total']} ({fmt_pct(r['name_accuracy'], 1)})" if r["name_total"] else "—",
            f"{r['sec_per_audio_min']:.2f}s",
            f"{r['realtime_factor_x']:.1f}×",
            r["delta_vram_mb"] if r["delta_vram_mb"] is not None else "—",
            f"{r['prompt_echo_count']}/{r['meetings_count']}" if r["use_prompt"] else "—",
            r.get("device", "—"),
        ]
        for r in summaries
    ]
    write_csv(out_dir / "exp1_stt.csv", headers, rows)

    per_meeting_sections: list[tuple[str, str]] = [("Bảng tổng hợp Thí nghiệm 1 — STT", markdown_table(headers, rows))]
    for r in summaries:
        sub_h = ["Cuộc họp", "Thời lượng", "Xử lý", "WER thô", "WER chuẩn hóa", "CER", "Đúng tên", "Lọc ảo giác"]
        sub_r = [
            [
                m["meeting_id"],
                f"{m['duration_sec']:.1f}s",
                f"{m['processing_sec']:.1f}s",
                fmt_pct(m["wer"]["wer_raw"], 2),
                fmt_pct(m["wer"]["wer_norm"], 2),
                fmt_pct(m["wer"]["cer_norm"], 2),
                f"{m['wer']['name_hits']}/{m['wer']['name_total']}" if m["wer"]["name_total"] else "—",
                m["dropped_count"],
            ]
            for m in r["per_meeting"]
        ]
        tag = "có gợi ý tên" if r["use_prompt"] else "không gợi ý tên"
        per_meeting_sections.append((f"Chi tiết: `{r['model']}` ({tag})", markdown_table(sub_h, sub_r)))

    notes = (
        "- `initial_prompt` chỉ tác động lên cửa sổ 30 giây đầu với faster-whisper (`condition_on_previous_text=False`) "
        "→ tác động lên WER toàn cuộc họp bị pha loãng; backend `hf:` áp dụng gợi ý cho mọi đoạn 30 giây.\n"
        "- \"Chép lại gợi ý\": số cuộc họp Whisper chép nguyên gợi ý vào bản ghi → MeetFlow tự chạy lại KHÔNG gợi ý, "
        "nên dòng \"có gợi ý\" của cuộc đó thực chất là kết quả không gợi ý.\n"
        "- VRAM = mức tăng so với nền lúc bắt đầu nạp mô hình (`nvidia-smi` đo toàn GPU); 1 lần đo chung cho cả 2 chế độ gợi ý.\n"
        "- WER chuẩn hóa: đổi số/ngày/giờ/%/phân cách nghìn sang chữ và quy cách đọc tương đương (tư/bốn, mốt/một, lẻ/linh, nghìn/ngàn) ở CẢ 2 phía.\n"
        "- Tỉ lệ đúng tên chỉ đếm các từ là tên thành viên VIẾT HOA trong bản chuẩn.\n"
        "- Pipeline: " + "; ".join(sorted({f"{r['model']}: {r.get('pipeline', '')}" for r in summaries}))
    )
    per_meeting_sections.insert(1, ("Ghi chú phương pháp", notes))
    if failed:
        per_meeting_sections.append(("Mô hình bị lỗi (không có số liệu)", "\n".join(f"- `{f['spec']}`: {f['error']}" for f in failed)))
    write_markdown(out_dir / "exp1_stt.md", "Kết quả Thí nghiệm 1 — So sánh mô hình STT tiếng Việt", per_meeting_sections)


def main() -> None:
    s = load_backend_settings()
    ap = argparse.ArgumentParser(description="Thí nghiệm 1 (GĐ7): So sánh mô hình STT tiếng Việt")
    ap.add_argument("--data", default=str(DEFAULT_DATA_DIR), help="Thư mục 1 cuộc họp hoặc thư mục cha chứa nhiều cuộc họp")
    ap.add_argument(
        "--models",
        nargs="+",
        default=["small", "medium", "large-v3-turbo"],
        help="Danh sách mô hình STT (VD: small medium large-v3-turbo hf:vinai/PhoWhisper-small)",
    )
    ap.add_argument("--ablate-prompt", action="store_true", help="Chạy cả CÓ và KHÔNG có `initial_prompt` (tên thành viên)")
    ap.add_argument("--no-prompt", action="store_true", help="Chỉ chạy KHÔNG có `initial_prompt`")
    ap.add_argument("--device", default=s.WHISPER_DEVICE, choices=["cuda", "cpu", "auto"])
    ap.add_argument("--compute-type", default=s.WHISPER_COMPUTE_TYPE)
    ap.add_argument("--out-dir", default=str(DEFAULT_RESULTS_DIR), help="Thư mục lưu báo cáo và bản ghi STT")
    ap.add_argument("--include-synthetic", action="store_true", help="Tính cả cuộc họp giả lập (synthetic: true, VD. TTS)")
    args = ap.parse_args()

    all_cases = select_cases(discover_meetings(Path(args.data)), args.include_synthetic)
    cases = [c for c in all_cases if c.has_audio and c.has_reference]
    if not cases:
        raise SystemExit("Không có cuộc họp nào có đủ cả file âm thanh và `reference.txt` để chấm STT.")

    skipped = [c.meeting_id for c in all_cases if c not in cases]
    if skipped:
        print(f"Bỏ qua {len(skipped)} cuộc họp thiếu audio hoặc reference.txt: {', '.join(skipped)}")

    prompt_modes = [True, False] if args.ablate_prompt else ([False] if args.no_prompt else [True])
    out_dir = Path(args.out_dir)
    transcripts_root = out_dir / "stt_transcripts"
    model_dir = str((Path(__file__).resolve().parents[1] / "backend" / s.WHISPER_MODEL_DIR).resolve())

    warn_roster(cases)
    summaries: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for spec in args.models:
        try:
            summaries.extend(
                evaluate_model_config(spec, cases, prompt_modes, args.device, args.compute_type, model_dir, transcripts_root)
            )
        except Exception as e:  # noqa: BLE001 — 1 mô hình lỗi không được làm mất kết quả các mô hình khác
            print(f"\n!!! Mô hình `{spec}` lỗi, bỏ qua: {type(e).__name__}: {e}")
            failed.append({"spec": spec, "error": f"{type(e).__name__}: {str(e)[:400]}"})
        export_exp1_reports(summaries, out_dir, failed)  # ghi lại sau MỖI mô hình
    print(f"\nĐã xuất kết quả TN1 tại: {out_dir / 'exp1_stt.md'}  |  {out_dir / 'exp1_stt.csv'}  |  {out_dir / 'exp1_stt.json'}")


if __name__ == "__main__":
    main()
