"""THÍ NGHIỆM 4 (Giai đoạn 7) — Đánh giá đóng góp riêng của phòng họp Online Meeting (GĐ6).

  - **Phần 4A — Nhãn người nói (`use_speakers=False` vs `True`):** cùng LLM (temperature 0), cùng bản
    ghi, chỉ khác có/không đưa nhãn người nói. Nguồn bản ghi chọn RÕ bằng `--transcript-source`:
      * `reference_speakers` (mặc định): bản ghi chuẩn do người gán, nhãn người nói chuẩn (oracle)
        → kết quả là CẬN TRÊN của lợi ích nhãn người nói;
      * `online_segments`: bản ghi + nhãn do chính Online Meeting sinh ra (có lỗi STT / lọc vọng).
    Lưu ý cách đọc kết quả: ở nhánh KHÔNG nhãn, prompt yêu cầu không đoán tên người tự nhận việc
    ("để em làm") nên hệ thống CỐ Ý bỏ trống → độ đúng trên việc tự nhận ≈ 0 theo thiết kế. Con số đo
    hành vi hệ thống GĐ4 vs GĐ6; lỗi được tách thành "bỏ trống" và "sai người".
    → `results/exp4_speakers.{json,csv,md}`.

  - **Phần 4B — Lọc tiếng vọng:**
    * KẾT QUẢ CHÍNH: dữ liệu thật `echo_eval.json` (nhãn `is_echo` gán MÙ — nghe track, không xem kết
      quả lọc), so **bản GĐ6 v1 (RMS thô, đóng băng trong file này)** với **bộ lọc hiện tại**
      (`speaker_merge.drop_echoes`, gọi như hộp đen) tại NGƯỠNG PRODUCTION. Quét ngưỡng 70–90 chỉ là
      phân tích độ nhạy (không chọn ngưỡng tốt nhất trên chính tập đánh giá).
    * `--synthetic-echo`: PHÂN TÍCH ĐỘ NHẠY / MINH HỌA trên dữ liệu mô phỏng — quét mức tiếng vọng
      10–80% và độ lệch mic 1, 2, 4, 6, 10×, có nhiễu RMS, nhiễu chữ, người nói có cả câu không bị vọng.
      Không dùng làm số liệu chính.
    → `results/exp4_echo.{json,csv,md}`.

Ví dụ (PowerShell, 1 dòng):
  backend\\.venv\\Scripts\\python experiments\\exp4_online.py --data experiments/data --models gemini:gemini-3.5-flash --sleep 2 --skip-existing
  backend\\.venv\\Scripts\\python experiments\\exp4_online.py --data experiments/data --echo-only --synthetic-echo
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import copy
import math
from pathlib import Path
import random
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BOOTSTRAP_SEED,
    DEFAULT_DATA_DIR,
    DEFAULT_RESULTS_DIR,
    MeetingCase,
    bootstrap_ci,
    discover_meetings,
    fmt_ci,
    fmt_pct,
    markdown_table,
    paired_bootstrap_delta,
    read_json,
    rnd,
    safe_div,
    select_cases,
    warn_roster,
    write_csv,
    write_json,
    write_markdown,
)
from eval_extraction import (  # noqa: E402
    aggregate_extraction_runs,
    build_llm,
    evaluate_cases_cached,
    stat_assignee_acc,
    stat_micro_f1,
    stat_self_claimed_recall,
    stat_strict_f1,
)
from exp2_llm import parse_llm_spec  # noqa: E402

from rapidfuzz import fuzz  # noqa: E402

from app.ai.postprocess import speaker_merge  # noqa: E402
from app.ai.postprocess.text_utils import norm_no_accent  # noqa: E402

TRANSCRIPT_SOURCES = ("reference_speakers", "online_segments")


# =============================================================================
# Phần 4A: Có vs Không có nhãn người nói
# =============================================================================


def speaker_cases(cases: list[MeetingCase], source: str) -> list[MeetingCase]:
    """Cuộc họp dùng được cho TN4A với nguồn bản ghi đã chọn."""
    if source == "online_segments":
        return [c for c in cases if c.has_expected_tasks and c.has_online_segments]
    return [c for c in cases if c.has_expected_tasks and c.has_speaker_reference]


def run_speaker_ablation(
    *,
    models: list[str],
    cases: list[MeetingCase],
    cache_dir: Path,
    skip_existing: bool,
    sleep_sec: float,
    allow_fallback: bool,
    transcript_source: str = "reference_speakers",
    run_id: str = "r1",
    llm_factory: Any = None,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for spec in models:
        provider, model = parse_llm_spec(spec)
        factory = llm_factory or (lambda p=provider, m=model: build_llm(p, m, allow_fallback=allow_fallback))
        pair: dict[str, dict[str, Any]] = {}
        for use_sp in (False, True):
            mode_key = "with_speakers" if use_sp else "without_speakers"
            label = f"{provider}/{model} ({'CÓ' if use_sp else 'KHÔNG'} nhãn người nói)"
            print(f"\n=== [TN4A] {label} — nguồn `{transcript_source}` ({len(cases)} cuộc họp) ===")

            def show(c: MeetingCase, row: dict[str, Any]) -> None:
                if row.get("failed"):
                    print(f"  [{c.meeting_id}] THẤT BẠI (tính mọi đầu việc là FN): {row['error']}")
                    return
                tag = " (cache)" if row.get("from_cache") else ""
                print(
                    f"  [{c.meeting_id}]{tag} F1={fmt_pct(row['f1'])} Strict={fmt_pct(row['strict_f1'])} | "
                    f"Người {row['assignee_correct']}/{row['tp']} (bỏ trống {row['assignee_blank']}, sai {row['assignee_wrong']}) | "
                    f"Tự nhận {row['self_claimed_correct']}/{row['self_claimed_expected']}"
                )

            rows = evaluate_cases_cached(
                cases=cases,
                llm_factory=factory,
                provider=provider,
                model=model,
                member_mode="full",
                use_speakers=use_sp,
                transcript_source=transcript_source,
                cache_dir=cache_dir,
                skip_existing=skip_existing,
                run_id=run_id,
                allow_fallback=allow_fallback,
                sleep_sec=sleep_sec if provider == "gemini" else 0.0,
                on_row=show,
            )
            pair[mode_key] = aggregate_extraction_runs(
                label,
                rows,
                meta={"provider": provider, "model": f"{provider}/{model}", "use_speakers": use_sp, "transcript_source": transcript_source, "run_id": run_id},
            )

        wo, wi = pair["without_speakers"], pair["with_speakers"]
        deltas = {
            key: paired_bootstrap_delta(wo["per_meeting"], wi["per_meeting"], fn)
            for key, fn in (
                ("f1", stat_micro_f1),
                ("strict_f1", stat_strict_f1),
                ("assignee_acc", stat_assignee_acc),
                ("self_claimed_recall", stat_self_claimed_recall),
            )
        }
        groups.append(
            {
                "llm": f"{provider}/{model}",
                "transcript_source": transcript_source,
                "without_speakers": wo,
                "with_speakers": wi,
                "deltas": deltas,
            }
        )
    return groups


_TN4A_NOTES = """- Hai nhánh dùng CÙNG bản ghi và cùng LLM (temperature 0); nhánh KHÔNG nhãn bỏ hết nhãn người nói khỏi prompt và hậu xử lý (kể cả nhãn khách không có tài khoản).
- Nguồn `reference_speakers` = nhãn người nói do người gán (oracle) → kết quả là cận trên; nguồn `online_segments` = nhãn thật do Online Meeting sinh ra.
- Ở nhánh KHÔNG nhãn, prompt cấm đoán tên người tự nhận việc → hệ thống cố ý bỏ trống; vì vậy "Việc tự nhận" gần 0 là do THIẾT KẾ. Kết quả so sánh hành vi hệ thống GĐ4 vs GĐ6, không phải "LLM giỏi hơn".
- "Việc tự nhận — recall" = số việc tự nhận được giao ĐÚNG người / tổng việc tự nhận trong đáp án (không phụ thuộc việc khớp tiêu đề).
- Δ = CÓ nhãn − KHÔNG nhãn; khoảng tin cậy 95% bootstrap ghép cặp theo cuộc họp."""


def export_exp4_speakers(groups: list[dict[str, Any]], out_dir: Path) -> None:
    write_json(out_dir / "exp4_speakers.json", {"experiment": "exp4_speakers", "groups": groups})
    headers = [
        "Cấu hình",
        "Nguồn bản ghi",
        "Số cuộc (lỗi)",
        "Micro F1 [95% CI]",
        "Strict F1 [95% CI]",
        "Đúng người (tổng)",
        "Lỗi người: bỏ trống / sai người",
        "Việc tự nhận: đúng / khớp",
        "Việc tự nhận: recall",
        "Tự nhận lỗi: bỏ trống / sai",
        "Khớp qua `speaker`",
        "Đúng hạn",
    ]
    rows: list[list[Any]] = []
    for g in groups:
        for r in (g["without_speakers"], g["with_speakers"]):
            rows.append(
                [
                    r["label"],
                    g["transcript_source"],
                    f"{r['meetings_count']} ({len(r.get('failed_meetings') or [])})",
                    f"{fmt_pct(r['micro_f1'])}{fmt_ci(r['micro_f1_ci95'])}",
                    f"{fmt_pct(r['strict_f1'])}{fmt_ci(r['strict_f1_ci95'])}",
                    f"{r['assignee_correct']}/{r['tp']} ({fmt_pct(r['assignee_acc'])})",
                    f"{r['assignee_blank']} / {r['assignee_wrong']}",
                    f"{r['self_claimed_correct']}/{r['self_claimed_matched']} ({fmt_pct(r['self_claimed_acc'])})",
                    f"{r['self_claimed_correct']}/{r['self_claimed_expected']} ({fmt_pct(r['self_claimed_recall'])})",
                    f"{r['self_claimed_blank']} / {r['self_claimed_wrong']}",
                    r["speaker_matched"],
                    f"{r['due_correct']}/{r['tp']} ({fmt_pct(r['due_acc'])})",
                ]
            )
    write_csv(out_dir / "exp4_speakers.csv", headers, rows)

    def dcell(d: dict[str, Any]) -> str:
        if d.get("delta") is None:
            return "—"
        ci = d.get("ci95")
        return f"**{d['delta'] * 100:+.1f} điểm %**" + (f" [{ci[0] * 100:+.1f}; {ci[1] * 100:+.1f}]" if ci else "")

    summary_lines = [
        f"- **`{g['llm']}`** (`{g['transcript_source']}`): ΔF1 {dcell(g['deltas']['f1'])} | ΔStrict F1 {dcell(g['deltas']['strict_f1'])} | "
        f"ΔĐúng người {dcell(g['deltas']['assignee_acc'])} | ΔRecall việc tự nhận {dcell(g['deltas']['self_claimed_recall'])}"
        for g in groups
    ]
    write_markdown(
        out_dir / "exp4_speakers.md",
        "Kết quả Thí nghiệm 4A — Tác động của nhãn người nói (Online Meeting)",
        [
            ("Bảng so sánh Có vs Không có nhãn người nói", markdown_table(headers, rows)),
            ("Mức thay đổi (Δ, khoảng tin cậy 95%)", "\n".join(summary_lines)),
            ("Cách đọc kết quả", _TN4A_NOTES),
        ],
    )


# =============================================================================
# Phần 4B: Lọc tiếng vọng — bản GĐ6 v1 (đóng băng) vs bộ lọc hiện tại (hộp đen)
# =============================================================================

# Hằng số của bản v1 (commit GĐ6 03f0df4) — chép cứng để mốc so sánh không đổi khi backend thay đổi
V1_SIMILARITY = 80
V1_MAX_SHIFT = 2.0
V1_MIN_CHARS = 12
MODES = ("v1_raw_rms", "current")
MODE_LABELS = {"v1_raw_rms": "Bản GĐ6 v1 (RMS thô)", "current": "Bộ lọc hiện tại"}


def production_similarity() -> int:
    return int(getattr(speaker_merge, "ECHO_SIMILARITY", 80))


def _v1_same_moment(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if abs(a["start"] - b["start"]) <= V1_MAX_SHIFT:
        return True
    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
    return overlap >= 0.5 * min(a["end"] - a["start"], b["end"] - b["start"]) > 0


def drop_echoes_v1(segments: list[dict[str, Any]], similarity: int = V1_SIMILARITY) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bộ lọc tiếng vọng bản GĐ6 v1 (chỉ so RMS thô `ra < rb`), đóng băng làm mốc so sánh cho TN4B."""
    segs = sorted(segments, key=lambda s: (s["start"], s["end"]))
    texts = [norm_no_accent(s["text"]) for s in segs]
    dropped: set[int] = set()
    for i, a in enumerate(segs):
        for j in range(i + 1, len(segs)):
            b = segs[j]
            if b["start"] > a["end"] + V1_MAX_SHIFT:
                break
            if i in dropped:
                break
            if j in dropped or a.get("speaker_id") == b.get("speaker_id"):
                continue
            if not _v1_same_moment(a, b):
                continue
            if min(len(texts[i]), len(texts[j])) < V1_MIN_CHARS:
                continue
            if max(fuzz.ratio(texts[i], texts[j]), fuzz.partial_ratio(texts[i], texts[j])) < similarity:
                continue
            ra, rb = a.get("rms"), b.get("rms")
            if ra is not None and rb is not None and ra != rb:
                a_is_echo = ra < rb
            elif len(a["text"]) != len(b["text"]):
                a_is_echo = len(a["text"]) < len(b["text"])
            else:
                a_is_echo = a["start"] > b["start"]
            dropped.add(i if a_is_echo else j)
    kept = [s for k, s in enumerate(segs) if k not in dropped]
    return kept, [segs[k] for k in sorted(dropped)]


def _drop_current(segments: list[dict[str, Any]], similarity: int | None) -> list[dict[str, Any]]:
    """Gọi bộ lọc hiện tại như hộp đen; chỉ đổi ngưỡng giống chữ nếu module có hằng số đó."""
    if similarity is None or not hasattr(speaker_merge, "ECHO_SIMILARITY"):
        return speaker_merge.drop_echoes(segments)[1]
    old = speaker_merge.ECHO_SIMILARITY
    speaker_merge.ECHO_SIMILARITY = similarity
    try:
        return speaker_merge.drop_echoes(segments)[1]
    finally:
        speaker_merge.ECHO_SIMILARITY = old


def _seg_key(s: dict[str, Any]) -> tuple[Any, ...]:
    return (s.get("start"), s.get("end"), s.get("text"), s.get("speaker_id"), s.get("track_id"))


def predict_dropped(segs: list[dict[str, Any]], mode: str, similarity: int | None = None) -> set[int]:
    """Chỉ số các câu bị lọc bỏ (theo thứ tự trong `segs`)."""
    tagged = [dict(s, _eval_id=i) for i, s in enumerate(segs)]
    work = copy.deepcopy(tagged)
    if mode == "v1_raw_rms":
        dropped = drop_echoes_v1(work, similarity if similarity is not None else V1_SIMILARITY)[1]
    elif mode == "current":
        dropped = _drop_current(work, similarity)
    else:
        raise ValueError(mode)
    by_key: dict[tuple[Any, ...], list[int]] = {}
    for s in tagged:
        by_key.setdefault(_seg_key(s), []).append(s["_eval_id"])
    out: set[int] = set()
    for d in dropped:
        if "_eval_id" in d:
            out.add(int(d["_eval_id"]))
        elif by_key.get(_seg_key(d)):
            out.add(by_key[_seg_key(d)].pop(0))
    return out


def _echo_counts(segs: list[dict[str, Any]], dropped: set[int]) -> dict[str, int]:
    c = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for i, s in enumerate(segs):
        truth, pred = bool(s.get("is_echo")), i in dropped
        c["tp" if truth and pred else "fp" if pred else "fn" if truth else "tn"] += 1
    return c


def _echo_metrics(c: dict[str, int]) -> dict[str, float | None]:
    tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
    return {
        "echo_precision": rnd(safe_div(tp, tp + fp)),
        "echo_recall": rnd(safe_div(tp, tp + fn)),
        "echo_f1": rnd(safe_div(2 * tp, 2 * tp + fp + fn)),
        "false_drop_rate": rnd(safe_div(fp, fp + tn)),
    }


def _sum_counts(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    return {k: sum(int(r[k]) for r in rows) for k in ("tp", "fp", "fn", "tn")}


def labelled_echo_datasets(cases: list[MeetingCase], verbose: bool = True) -> list[tuple[str, list[dict[str, Any]]]]:
    """Đọc `echo_eval.json`; chỉ nhận cuộc họp mà MỌI câu đã gán nhãn `is_echo` true/false."""
    out: list[tuple[str, list[dict[str, Any]]]] = []
    for c in cases:
        if not c.echo_eval_path:
            continue
        raw = read_json(c.echo_eval_path)
        segs = raw.get("segments", []) if isinstance(raw, dict) else raw
        segs = [s for s in segs if str(s.get("text", "")).strip() and s.get("start") is not None and s.get("end") is not None]
        unl = sum(1 for s in segs if not isinstance(s.get("is_echo"), bool))
        if not segs:
            continue
        if unl:
            if verbose:
                print(f"  Bỏ qua `{c.meeting_id}`: còn {unl}/{len(segs)} câu chưa gán nhãn is_echo.")
            continue
        out.append((c.meeting_id, segs))
    return out


def score_echo_dataset(labeled: list[tuple[str, list[dict[str, Any]]]], mode: str, similarity: int | None = None, with_ci: bool = False) -> dict[str, Any]:
    """Echo Precision / Recall / F1 và tỉ lệ bỏ nhầm câu thật (FDR), gộp nhiều cuộc họp (micro)."""
    per = []
    for mid, segs in labeled:
        counts = _echo_counts(segs, predict_dropped(segs, mode, similarity))
        per.append({"meeting_id": mid, **counts})
    tot = _sum_counts(per)
    row: dict[str, Any] = {
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "similarity_threshold": similarity if similarity is not None else (V1_SIMILARITY if mode == "v1_raw_rms" else production_similarity()),
        "meetings_count": len(labeled),
        "real_segments": tot["fp"] + tot["tn"],
        "echo_segments": tot["tp"] + tot["fn"],
        **tot,
        **_echo_metrics(tot),
        "per_meeting": per,
    }
    if with_ci:
        row["echo_f1_ci95"] = bootstrap_ci(per, lambda rs: _echo_metrics(_sum_counts(rs))["echo_f1"])
        row["false_drop_rate_ci95"] = bootstrap_ci(per, lambda rs: _echo_metrics(_sum_counts(rs))["false_drop_rate"])
    return row


# ---- Phân tích độ nhạy trên dữ liệu mô phỏng (MINH HỌA, không phải số liệu chính) ----

_SYN_SCRIPT: list[tuple[int, str]] = [
    (1, "Chào mọi người, mình bắt đầu buổi họp tuần của nhóm nhé."),
    (2, "Dạ em đã hoàn thành phần khảo sát sản phẩm tương tự rồi ạ."),
    (1, "Tốt, vậy Lan viết chương hai phần cơ sở lý thuyết về nhận dạng giọng nói nhé."),
    (2, "Vâng, thứ Sáu tuần này em gửi bản nháp cho anh ạ."),
    (3, "Phần giao diện trang cuộc họp và trình phát âm thanh em đang làm dở ạ."),
    (1, "Ừ, Minh hoàn thành trình phát âm thanh trước ngày hai mươi lăm tháng mười một nhé."),
    (3, "Dạ được ạ, để em tranh thủ làm xong trong tuần này luôn."),
    (1, "Còn phần anh, anh sẽ chuẩn bị bộ dữ liệu thực nghiệm gồm mười lăm cuộc họp."),
    (2, "Anh ơi mình có cần gửi email hẹn lịch demo cho thầy hướng dẫn không ạ?"),
    (1, "Có, Lan gửi email hẹn lịch demo cho thầy trong ngày mai giúp anh nhé."),
    (3, "Nhóm mình thống nhất dùng PostgreSQL và Redis cho phần hàng đợi phải không anh?"),
    (1, "Đúng rồi, chốt lại như vậy, còn phần triển khai thì để tuần sau bàn tiếp."),
    (2, "Em sẽ cập nhật lại bảng công việc sau buổi họp hôm nay ạ."),
    (1, "Minh nhớ viết thêm kiểm thử cho phần đồng bộ bản ghi với âm thanh nhé."),
    (3, "Vâng anh, em sẽ bổ sung kiểm thử và gửi lên nhánh chính."),
    (1, "Chiều thứ Sáu nhóm họp kiểm tra tiến độ, mọi người nhớ tham gia đầy đủ nhé."),
]
_SYN_NAMES = {1: "Nguyễn Văn Nam", 2: "Trần Thị Lan", 3: "Lê Quang Minh"}
_NOISE_WORDS = ["ừ", "à", "thì", "là", "cái", "nha", "nhé", "vậy"]


def _noisy_echo_text(text: str, rng: random.Random) -> str:
    """Bản vọng qua STT: hay mất từ đầu, rơi vài từ, lẫn vài từ đệm."""
    words = text.split()
    if len(words) > 4 and rng.random() < 0.5:
        words = words[1:]
    kept = [w for w in words if rng.random() >= 0.08] or words[:1]
    out: list[str] = []
    for w in kept:
        out.append(rng.choice(_NOISE_WORDS) if rng.random() < 0.05 else w)
    return " ".join(out)


def synthetic_meeting(echo_level: float, gain: float, rng: random.Random, p_echo: float = 0.7, jitter: float = 0.2) -> list[dict[str, Any]]:
    """1 cuộc họp mô phỏng: Lan nghe loa ngoài nên mic Lan thu lại một phần (p_echo) câu của Nam & Minh.

    - Mic Lan nhạy gấp `gain` lần mic Nam; tiếng vọng = `echo_level` × mức giọng thường của mic Lan.
    - RMS mỗi câu dao động ngẫu nhiên (log-normal, σ = `jitter`), độ trễ vọng 0,15–0,6 giây.
    - Nam & Minh có cả câu KHÔNG bị vọng (để có mức giọng nền riêng), Lan không bao giờ bị vọng sang mic khác.
    """
    base = {1: 0.025, 2: 0.025 * gain, 3: 0.05}
    segs: list[dict[str, Any]] = []
    t = 0.0
    for sp, text in _SYN_SCRIPT:
        dur = 2.5 + 0.06 * len(text.split())
        segs.append(
            {
                "start": round(t, 2),
                "end": round(t + dur, 2),
                "text": text,
                "speaker_id": sp,
                "speaker": _SYN_NAMES[sp],
                "track_id": sp,
                "rms": round(base[sp] * math.exp(rng.gauss(0, jitter)), 6),
                "is_echo": False,
            }
        )
        if sp != 2 and rng.random() < p_echo:
            delay = rng.uniform(0.15, 0.6)
            segs.append(
                {
                    "start": round(t + delay, 2),
                    "end": round(t + dur + delay + rng.uniform(-0.1, 0.1), 2),
                    "text": _noisy_echo_text(text, rng),
                    "speaker_id": 2,
                    "speaker": _SYN_NAMES[2],
                    "track_id": 2,
                    "rms": round(base[2] * echo_level * math.exp(rng.gauss(0, jitter)), 6),
                    "is_echo": True,
                }
            )
        t += dur + rng.uniform(0.8, 2.0)
    return segs


def build_synthetic_sensitivity(
    echo_levels: Sequence[float] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8),
    gains: Sequence[float] = (1.0, 2.0, 4.0, 6.0, 10.0),
    reps: int = 5,
    seed: int = BOOTSTRAP_SEED,
) -> list[dict[str, Any]]:
    """Quét (mức tiếng vọng × độ lệch mic), mỗi ô `reps` cuộc họp mô phỏng; cả 2 bộ lọc chấm trên CÙNG dữ liệu."""
    rows: list[dict[str, Any]] = []
    for level in echo_levels:
        for gain in gains:
            rng = random.Random(f"{seed}-{level}-{gain}")
            meetings = [(f"syn_{level:g}_{gain:g}_{k}", synthetic_meeting(level, gain, rng)) for k in range(reps)]
            for mode in MODES:
                sc = score_echo_dataset(meetings, mode=mode)
                sc.pop("per_meeting", None)
                rows.append({**sc, "echo_level": level, "gain_ratio": gain, "reps": reps, "seed": seed})
    return rows


def export_exp4_echo(
    headline_rows: list[dict[str, Any]],
    sweep_rows: list[dict[str, Any]],
    synthetic_rows: list[dict[str, Any]],
    out_dir: Path,
) -> None:
    write_json(
        out_dir / "exp4_echo.json",
        {
            "experiment": "exp4_echo",
            "production_similarity": production_similarity(),
            "real_data_headline": headline_rows,
            "real_data_threshold_sensitivity": sweep_rows,
            "synthetic_sensitivity": synthetic_rows,
        },
    )
    headers = ["Tập đo", "Bộ lọc", "Ngưỡng / Kịch bản", "Câu thật", "Câu vọng", "TP / FP / FN", "Echo P", "Echo R", "Echo F1 [95% CI]", "Bỏ nhầm câu thật (FDR) [95% CI]"]

    def line(kind: str, r: dict[str, Any], scen: str) -> list[Any]:
        return [
            kind,
            r["mode_label"],
            scen,
            r["real_segments"],
            r["echo_segments"],
            f"{r['tp']} / {r['fp']} / {r['fn']}",
            fmt_pct(r["echo_precision"]),
            fmt_pct(r["echo_recall"]),
            f"{fmt_pct(r['echo_f1'])}{fmt_ci(r.get('echo_f1_ci95'))}",
            f"{fmt_pct(r['false_drop_rate'])}{fmt_ci(r.get('false_drop_rate_ci95'))}",
        ]

    sections: list[tuple[str, str]] = []
    csv_rows: list[list[Any]] = []
    if headline_rows:
        rows = [line("Dữ liệu thật — KẾT QUẢ CHÍNH", r, f"sim ≥ {r['similarity_threshold']}%") for r in headline_rows]
        csv_rows.extend(rows)
        sections.append(
            (
                f"Kết quả chính: dữ liệu Online Meeting thật (`echo_eval.json`, ngưỡng production {production_similarity()}%)",
                "_Nhãn `is_echo` gán mù (nghe track, không xem kết quả lọc). Khoảng tin cậy = bootstrap theo cuộc họp._\n\n" + markdown_table(headers, rows),
            )
        )
    if sweep_rows:
        rows = [line("Dữ liệu thật — độ nhạy", r, f"sim ≥ {r['similarity_threshold']}%") for r in sweep_rows]
        csv_rows.extend(rows)
        sections.append(
            (
                "Phân tích độ nhạy theo ngưỡng giống chữ (KHÔNG dùng để chọn ngưỡng)",
                "_Chỉ để xem kết quả có ổn định quanh ngưỡng production hay không; chọn ngưỡng tốt nhất trên chính tập này là tinh chỉnh trên tập kiểm tra._\n\n"
                + markdown_table(headers, rows),
            )
        )
    if synthetic_rows:
        rows = [line("Mô phỏng (minh họa)", r, f"vọng {r['echo_level'] * 100:.0f}% · mic lệch {r['gain_ratio']:g}× · {r['reps']} cuộc") for r in synthetic_rows]
        csv_rows.extend(rows)
        sections.append(
            (
                "Phân tích độ nhạy trên dữ liệu mô phỏng (MINH HỌA — không phải số liệu chính)",
                "_Dữ liệu sinh ngẫu nhiên (hạt giống cố định): mức tiếng vọng 10–80% giọng thường của mic nghe loa ngoài, "
                "độ lệch độ nhạy mic 1–10×, nhiễu RMS log-normal σ=0,2, nhiễu chữ, người nói có cả câu không bị vọng. "
                "Kết quả phụ thuộc giả định mô phỏng nên chỉ dùng để minh họa xu hướng._\n\n" + markdown_table(headers, rows),
            )
        )
    write_csv(out_dir / "exp4_echo.csv", headers, csv_rows)
    write_markdown(out_dir / "exp4_echo.md", "Kết quả Thí nghiệm 4B — Đánh giá thuật toán lọc tiếng vọng", sections)


def main() -> None:
    ap = argparse.ArgumentParser(description="Thí nghiệm 4 (GĐ7): Nhãn người nói & Lọc tiếng vọng (Online Meeting)")
    ap.add_argument("--data", default=str(DEFAULT_DATA_DIR), help="Thư mục dữ liệu (1 hoặc nhiều cuộc họp)")
    ap.add_argument("--models", nargs="+", default=["gemini:gemini-3.5-flash"], help="Danh sách `<provider>:<model>` cho TN4A")
    ap.add_argument(
        "--transcript-source",
        choices=TRANSCRIPT_SOURCES,
        default="reference_speakers",
        help="TN4A: reference_speakers (bản chuẩn + nhãn người gán, cận trên) | online_segments (bản ghi + nhãn do Online Meeting sinh)",
    )
    ap.add_argument("--echo-only", action="store_true", help="Chỉ chạy phần 4B (lọc tiếng vọng), không gọi LLM")
    ap.add_argument("--synthetic-echo", action="store_true", help="Chạy thêm phân tích độ nhạy trên dữ liệu mô phỏng (minh họa)")
    ap.add_argument("--thresholds", nargs="+", type=int, default=[70, 75, 80, 85, 90], help="Các ngưỡng giống chữ cho phân tích độ nhạy")
    ap.add_argument("--echo-levels", nargs="+", type=float, default=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    ap.add_argument("--gains", nargs="+", type=float, default=[1.0, 2.0, 4.0, 6.0, 10.0])
    ap.add_argument("--reps", type=int, default=5, help="Số cuộc họp mô phỏng mỗi ô")
    ap.add_argument("--allow-fallback", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--run-id", default="r1")
    ap.add_argument("--include-synthetic", action="store_true", help="Tính cả cuộc họp giả lập (synthetic: true)")
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument("--out-dir", default=str(DEFAULT_RESULTS_DIR))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    all_cases = select_cases(discover_meetings(Path(args.data)), args.include_synthetic)

    if not args.echo_only:
        sp_cases = speaker_cases(all_cases, args.transcript_source)
        if sp_cases:
            warn_roster(sp_cases)
            groups = run_speaker_ablation(
                models=args.models,
                cases=sp_cases,
                cache_dir=out_dir / "cache",
                skip_existing=args.skip_existing,
                sleep_sec=args.sleep,
                allow_fallback=args.allow_fallback,
                transcript_source=args.transcript_source,
                run_id=args.run_id,
            )
            export_exp4_speakers(groups, out_dir)
            print(f"\nĐã xuất TN4A tại: {out_dir / 'exp4_speakers.md'} | {out_dir / 'exp4_speakers.csv'}")
        else:
            print(f"Không có cuộc họp nào (đã gán nhãn) có nguồn `{args.transcript_source}` cho TN4A.")

    print("\n=== [TN4B] Lọc tiếng vọng ===")
    labelled = labelled_echo_datasets(all_cases)
    headline: list[dict[str, Any]] = []
    sweep: list[dict[str, Any]] = []
    if labelled:
        prod = production_similarity()
        for mode in MODES:
            r = score_echo_dataset(labelled, mode=mode, similarity=prod, with_ci=True)
            headline.append(r)
            print(f"  KẾT QUẢ CHÍNH sim≥{prod}% | {MODE_LABELS[mode]:22s} | Echo F1={fmt_pct(r['echo_f1'])}{fmt_ci(r['echo_f1_ci95'])} | FDR={fmt_pct(r['false_drop_rate'])}")
        for th in args.thresholds:
            for mode in MODES:
                sweep.append(score_echo_dataset(labelled, mode=mode, similarity=th))
    else:
        print("  Chưa có `echo_eval.json` nào đã gán nhãn đủ → chưa có kết quả chính cho TN4B.")

    synthetic: list[dict[str, Any]] = []
    if args.synthetic_echo:
        print("  Phân tích độ nhạy trên dữ liệu mô phỏng (minh họa)...")
        synthetic = build_synthetic_sensitivity(args.echo_levels, args.gains, args.reps)

    if headline or sweep or synthetic:
        export_exp4_echo(headline, sweep, synthetic, out_dir)
        print(f"Đã xuất TN4B tại: {out_dir / 'exp4_echo.md'} | {out_dir / 'exp4_echo.csv'}")


if __name__ == "__main__":
    main()
