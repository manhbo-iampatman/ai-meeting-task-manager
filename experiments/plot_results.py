"""Sinh bộ biểu đồ 300 DPI (chuẩn tiếng Việt) cho Chương 4 báo cáo khóa luận.

Đọc các file JSON kết quả trong `experiments/results/` (file nào có thì vẽ biểu đồ đó) và lưu PNG vào
`experiments/results/charts/`:
  - `chart1_stt_wer_speed.png`               : TN1 — WER (thô & chuẩn hóa), tốc độ, VRAM tăng thêm
  - `chart1b_stt_prompt_effect.png`          : TN1 — có / không `initial_prompt` (WER + tỉ lệ đúng tên)
  - `chart2_llm_comparison.png`              : TN2 — P / R / F1 / Strict F1 (kèm CI 95%) / Đúng người / Đúng hạn
  - `chart2b_match_threshold_sensitivity.png`: TN2 — độ nhạy của F1 theo ngưỡng ghép tiêu đề
  - `chart3_e2e_propagation.png`             : TN3 — bản chuẩn vs bản STT trên cùng tập cuộc họp
  - `chart4a_speaker_labels.png`             : TN4A — có vs không nhãn người nói
  - `chart4b_echo_real.png`                  : TN4B — kết quả chính (ngưỡng production) + độ nhạy ngưỡng
  - `chart4c_echo_synthetic_sensitivity.png` : TN4B — phân tích độ nhạy trên dữ liệu mô phỏng (minh họa)

Cách dùng:
  backend\\.venv\\Scripts\\python experiments\\plot_results.py
  backend\\.venv\\Scripts\\python experiments\\plot_results.py --results-dir experiments/results
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from common import DEFAULT_RESULTS_DIR  # noqa: E402

C_BLUE = "#2563EB"
C_TEAL = "#0D9488"
C_AMBER = "#D97706"
C_ROSE = "#E11D48"
C_SLATE = "#64748B"
C_INDIGO = "#4F46E5"
C_VIOLET = "#7C3AED"


def _configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
            "axes.edgecolor": "#CBD5E1",
            "axes.linewidth": 0.9,
            "axes.grid": True,
            "grid.color": "#E2E8F0",
            "grid.linestyle": "--",
            "grid.alpha": 0.8,
            "axes.axisbelow": True,
            "figure.dpi": 150,
            "savefig.dpi": 300,
        }
    )


def _pct(v: float | None) -> float:
    """Tỉ lệ → %, None (không định nghĩa) → NaN để cột trống thay vì vẽ 0% gây hiểu nhầm."""
    return float("nan") if v is None else v * 100.0


def _err(values: list[float], cis: list[list[float] | None]) -> np.ndarray | None:
    """Thanh sai số từ khoảng tin cậy 95% (None → không vẽ)."""
    if not any(cis):
        return None
    lo, hi = [], []
    for v, ci in zip(values, cis, strict=True):
        if ci is None or math.isnan(v):
            lo.append(0.0)
            hi.append(0.0)
        else:
            lo.append(max(0.0, v - ci[0] * 100))
            hi.append(max(0.0, ci[1] * 100 - v))
    return np.array([lo, hi])


def _label_bars(ax: Any, bars: Any, fmt: str = "{:.1f}%", offset: float = 1.2, fontsize: int = 8) -> None:
    for b in bars:
        h = b.get_height()
        if h is None or math.isnan(h):
            ax.text(b.get_x() + b.get_width() / 2.0, offset, "—", ha="center", va="bottom", fontsize=fontsize, color="#94A3B8")
            continue
        ax.text(b.get_x() + b.get_width() / 2.0, h + offset, fmt.format(h), ha="center", va="bottom", fontsize=fontsize, color="#1E293B")


def _short_model(name: str) -> str:
    return name.replace("faster-whisper/", "FW ").replace("hf/vinai/", "").replace("gemini/", "").replace("ollama/", "")


def plot_exp1_stt(data: dict[str, Any], charts_dir: Path) -> list[Path]:
    runs = data.get("runs") or []
    if not runs:
        return []
    saved: list[Path] = []
    main_runs = [r for r in runs if r.get("use_prompt")] or runs
    labels = [_short_model(r["model"]) for r in main_runs]
    wer_raw = [r["micro_wer_raw"] * 100 for r in main_runs]
    wer_norm = [r["micro_wer_norm"] * 100 for r in main_runs]
    sec_per_min = [r["sec_per_audio_min"] for r in main_runs]
    vrams = [r.get("delta_vram_mb") for r in main_runs]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.8))
    x = np.arange(len(labels))
    w = 0.36
    b1 = ax1.bar(x - w / 2, wer_raw, w, label="WER thô", color=C_SLATE, alpha=0.85)
    b2 = ax1.bar(x + w / 2, wer_norm, w, label="WER chuẩn hóa số", color=C_BLUE)
    _label_bars(ax1, b1, "{:.1f}%", offset=0.5)
    _label_bars(ax1, b2, "{:.1f}%", offset=0.5)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=15, ha="right")
    ax1.set_ylabel("WER (%) — càng thấp càng tốt")
    ax1.set_title("Độ lỗi từ (WER) theo mô hình STT")
    ax1.set_ylim(0, max(wer_raw + wer_norm + [5.0]) * 1.25)
    ax1.legend(frameon=False)

    b3 = ax2.bar(x, sec_per_min, 0.52, color=C_TEAL)
    for bar, vram in zip(b3, vrams, strict=True):
        h = bar.get_height()
        v_txt = f"\n(+{vram} MB VRAM)" if vram is not None else ""
        ax2.text(bar.get_x() + bar.get_width() / 2.0, h + max(sec_per_min + [1.0]) * 0.03, f"{h:.1f}s{v_txt}", ha="center", va="bottom", fontsize=8, color="#1E293B")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=15, ha="right")
    ax2.set_ylabel("Giây xử lý / 1 phút audio — càng thấp càng nhanh")
    ax2.set_title("Tốc độ xử lý & VRAM tăng thêm")
    ax2.set_ylim(0, max(sec_per_min + [1.0]) * 1.32)

    fig.suptitle("Thí nghiệm 1 — So sánh các mô hình nhận dạng giọng nói tiếng Việt", fontsize=12, fontweight="bold")
    fig.tight_layout()
    p1 = charts_dir / "chart1_stt_wer_speed.png"
    fig.savefig(p1)
    plt.close(fig)
    saved.append(p1)

    by_model: dict[str, dict[bool, dict[str, Any]]] = {}
    for r in runs:
        by_model.setdefault(r["model"], {})[bool(r.get("use_prompt"))] = r
    paired = [(m, d[False], d[True]) for m, d in by_model.items() if False in d and True in d]
    if paired:
        p_labels = [_short_model(m) for m, _, _ in paired]
        wer_no = [no["micro_wer_norm"] * 100 for _, no, _ in paired]
        wer_yes = [yes["micro_wer_norm"] * 100 for _, _, yes in paired]
        name_no = [_pct(no.get("name_accuracy")) for _, no, _ in paired]
        name_yes = [_pct(yes.get("name_accuracy")) for _, _, yes in paired]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.6))
        xp = np.arange(len(p_labels))
        w = 0.35
        b1 = ax1.bar(xp - w / 2, wer_no, w, label="Không gợi ý tên", color=C_SLATE)
        b2 = ax1.bar(xp + w / 2, wer_yes, w, label="Có gợi ý tên thành viên", color=C_BLUE)
        _label_bars(ax1, b1, "{:.1f}%", offset=0.4)
        _label_bars(ax1, b2, "{:.1f}%", offset=0.4)
        ax1.set_xticks(xp)
        ax1.set_xticklabels(p_labels, rotation=12, ha="right")
        ax1.set_ylabel("WER chuẩn hóa (%) — thấp hơn tốt hơn")
        ax1.set_title("Ảnh hưởng lên WER tổng thể")
        ax1.set_ylim(0, max(wer_no + wer_yes + [5.0]) * 1.25)
        ax1.legend(frameon=False)

        b3 = ax2.bar(xp - w / 2, name_no, w, label="Không gợi ý tên", color=C_SLATE)
        b4 = ax2.bar(xp + w / 2, name_yes, w, label="Có gợi ý tên thành viên", color=C_TEAL)
        _label_bars(ax2, b3, "{:.0f}%", offset=1.5)
        _label_bars(ax2, b4, "{:.0f}%", offset=1.5)
        ax2.set_xticks(xp)
        ax2.set_xticklabels(p_labels, rotation=12, ha="right")
        ax2.set_ylabel("Tỉ lệ nhận đúng tên thành viên (%)")
        ax2.set_title("Ảnh hưởng lên độ đúng tên thành viên")
        ax2.set_ylim(0, 115)
        ax2.legend(frameon=False)

        fig.suptitle("Thí nghiệm 1B — Tác động của `initial_prompt` (chỉ tác động cửa sổ 30 giây đầu)", fontsize=12, fontweight="bold")
        fig.tight_layout()
        p1b = charts_dir / "chart1b_stt_prompt_effect.png"
        fig.savefig(p1b)
        plt.close(fig)
        saved.append(p1b)
    return saved


def plot_exp2_llm(data: dict[str, Any], charts_dir: Path) -> list[Path]:
    runs = data.get("runs") or []
    if not runs:
        return []
    saved: list[Path] = []
    labels = [_short_model(r["label"]) for r in runs]
    metrics = [
        ("Precision", "micro_precision", C_SLATE),
        ("Recall", "micro_recall", C_INDIGO),
        ("F1 (tiêu đề)", "micro_f1", C_BLUE),
        ("Strict F1 (end-to-end)", "strict_f1", C_VIOLET),
        ("Đúng người (cặp đã khớp)", "assignee_acc", C_TEAL),
        ("Đúng hạn (việc có hạn)", "due_with_date_acc", C_AMBER),
    ]
    fig, ax = plt.subplots(figsize=(max(10.0, 2.6 * len(labels)), 5.2))
    x = np.arange(len(labels))
    w = 0.13
    offsets = np.linspace(-2.5 * w, 2.5 * w, len(metrics))
    for (name, key, color), off in zip(metrics, offsets, strict=True):
        vals = [_pct(r.get(key)) for r in runs]
        err = _err(vals, [r.get(key + "_ci95") for r in runs])
        bars = ax.bar(x + off, vals, w, label=name, color=color, yerr=err, capsize=2, error_kw={"elinewidth": 0.8, "ecolor": "#334155"})
        _label_bars(ax, bars, "{:.0f}", offset=1.2, fontsize=6)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=12, ha="right")
    ax.set_ylabel("Tỉ lệ (%) — thanh đen: khoảng tin cậy 95% (bootstrap theo cuộc họp)")
    ax.set_ylim(0, 118)
    ax.set_title("Thí nghiệm 2 — So sánh chất lượng trích xuất đầu việc giữa các cấu hình LLM", fontweight="bold")
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.18), frameon=False)
    fig.tight_layout()
    out = charts_dir / "chart2_llm_comparison.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    saved.append(out)

    sens_runs = [r for r in runs if r.get("threshold_sensitivity")]
    if sens_runs:
        fig, ax = plt.subplots(figsize=(8.6, 4.6))
        palette = [C_BLUE, C_TEAL, C_AMBER, C_ROSE, C_INDIGO, C_SLATE, C_VIOLET]
        for idx, r in enumerate(sens_runs):
            ths = sorted(int(k) for k in r["threshold_sensitivity"])
            ys = [_pct(r["threshold_sensitivity"][str(t)]["f1"]) for t in ths]
            ax.plot(ths, ys, marker="o", linewidth=2, color=palette[idx % len(palette)], label=_short_model(r["label"]))
        ax.axvline(r.get("title_threshold", 60), color="#94A3B8", linestyle=":", linewidth=1.2)
        ax.set_xlabel("Ngưỡng ghép tiêu đề token_set_ratio (đường chấm = ngưỡng dùng trong báo cáo)")
        ax.set_ylabel("Micro F1 (%)")
        ax.set_ylim(-5, 105)
        ax.set_title("Thí nghiệm 2 — Độ nhạy của F1 theo ngưỡng ghép tiêu đề", fontweight="bold")
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        out = charts_dir / "chart2b_match_threshold_sensitivity.png"
        fig.savefig(out)
        plt.close(fig)
        saved.append(out)
    return saved


def plot_exp3_e2e(data: dict[str, Any], charts_dir: Path) -> list[Path]:
    groups = data.get("groups") or []
    runs: list[dict[str, Any]] = []
    labels: list[str] = []
    for g in groups:
        for comp in g.get("comparisons") or []:
            stt_name = comp["stt_source"].replace("faster-whisper__", "FW ").replace("__prompt", "")
            runs += [comp["gold"], comp["stt"]]
            labels += [f"{_short_model(g['llm'])}\n(Bản chuẩn, {comp['gold']['meetings_count']} cuộc)", f"{_short_model(g['llm'])}\n+ {stt_name}"]
    if not runs:
        return []
    metrics = [("F1 (tiêu đề)", "micro_f1", C_BLUE), ("Strict F1", "strict_f1", C_VIOLET), ("Đúng người", "assignee_acc", C_TEAL), ("Đúng hạn", "due_acc", C_AMBER)]
    fig, ax = plt.subplots(figsize=(max(8.5, 2.4 * len(labels)), 4.9))
    x = np.arange(len(labels))
    w = 0.2
    for idx, (name, key, color) in enumerate(metrics):
        vals = [_pct(r.get(key)) for r in runs]
        err = _err(vals, [r.get(key + "_ci95") for r in runs])
        bars = ax.bar(x + (idx - 1.5) * w, vals, w, label=name, color=color, yerr=err, capsize=2, error_kw={"elinewidth": 0.8, "ecolor": "#334155"})
        _label_bars(ax, bars, "{:.0f}%", offset=1.2, fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Tỉ lệ (%)")
    ax.set_ylim(0, 118)
    ax.set_title("Thí nghiệm 3 — Lan truyền lỗi End-to-End (cùng tập cuộc họp)", fontweight="bold")
    ax.legend(frameon=False, loc="upper right", ncol=2)
    fig.tight_layout()
    out = charts_dir / "chart3_e2e_propagation.png"
    fig.savefig(out)
    plt.close(fig)
    return [out]


def plot_exp4_speakers(data: dict[str, Any], charts_dir: Path) -> list[Path]:
    groups = data.get("groups") or []
    if not groups:
        return []
    cats = [("F1 (tiêu đề)", "micro_f1"), ("Strict F1", "strict_f1"), ("Đúng người\n(cặp đã khớp)", "assignee_acc"), ("Việc tự nhận\n(recall)", "self_claimed_recall")]
    fig, axes = plt.subplots(1, len(groups), figsize=(8.8 * len(groups), 4.9), squeeze=False)
    for ax, g in zip(axes[0], groups, strict=True):
        wo, wi = g["without_speakers"], g["with_speakers"]
        x = np.arange(len(cats))
        w = 0.34
        v_wo = [_pct(wo.get(k)) for _, k in cats]
        v_wi = [_pct(wi.get(k)) for _, k in cats]
        e_wo = _err(v_wo, [wo.get(k + "_ci95") for _, k in cats])
        e_wi = _err(v_wi, [wi.get(k + "_ci95") for _, k in cats])
        b1 = ax.bar(x - w / 2, v_wo, w, label="Không nhãn người nói (như file ghi âm GĐ4)", color=C_SLATE, yerr=e_wo, capsize=2)
        b2 = ax.bar(x + w / 2, v_wi, w, label="Có nhãn người nói (Online Meeting GĐ6)", color=C_BLUE, yerr=e_wi, capsize=2)
        _label_bars(ax, b1, "{:.1f}%", offset=1.5)
        _label_bars(ax, b2, "{:.1f}%", offset=1.5)
        ax.set_xticks(x)
        ax.set_xticklabels([c for c, _ in cats], fontsize=8)
        ax.set_ylabel("Tỉ lệ (%)")
        ax.set_ylim(0, 120)
        src = "nhãn chuẩn — cận trên" if g.get("transcript_source") == "reference_speakers" else "nhãn Online Meeting"
        ax.set_title(f"{_short_model(g['llm'])} ({src})", fontsize=10)
        ax.legend(frameon=False, loc="upper left", fontsize=8)
    fig.suptitle("Thí nghiệm 4A — Tác động của nhãn người nói", fontsize=12, fontweight="bold")
    fig.tight_layout()
    out = charts_dir / "chart4a_speaker_labels.png"
    fig.savefig(out)
    plt.close(fig)
    return [out]


_MODE_STYLE = {"v1_raw_rms": ("Bản GĐ6 v1 (RMS thô)", C_ROSE, "s"), "current": ("Bộ lọc hiện tại", C_BLUE, "o")}


def plot_exp4_echo(data: dict[str, Any], charts_dir: Path) -> list[Path]:
    saved: list[Path] = []
    headline = data.get("real_data_headline") or []
    sweep = data.get("real_data_threshold_sensitivity") or []
    if headline or sweep:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.5))
        if headline:
            names = [_MODE_STYLE[r["mode"]][0] for r in headline]
            x = np.arange(len(headline))
            f1 = [_pct(r["echo_f1"]) for r in headline]
            fdr = [_pct(r["false_drop_rate"]) for r in headline]
            b1 = ax1.bar(x - 0.18, f1, 0.36, color=C_BLUE, label="Echo F1", yerr=_err(f1, [r.get("echo_f1_ci95") for r in headline]), capsize=3)
            b2 = ax1.bar(x + 0.18, fdr, 0.36, color=C_ROSE, label="Bỏ nhầm câu thật (FDR)", yerr=_err(fdr, [r.get("false_drop_rate_ci95") for r in headline]), capsize=3)
            _label_bars(ax1, b1)
            _label_bars(ax1, b2)
            ax1.set_xticks(x)
            ax1.set_xticklabels(names)
            ax1.set_ylim(0, 115)
            ax1.set_title(f"Kết quả chính — ngưỡng production {data.get('production_similarity', 80)}%")
            ax1.legend(frameon=False, fontsize=8)
        for mode, (label, color, marker) in _MODE_STYLE.items():
            sub = sorted([r for r in sweep if r["mode"] == mode], key=lambda r: r["similarity_threshold"])
            if sub:
                xs = [r["similarity_threshold"] for r in sub]
                ax2.plot(xs, [_pct(r["echo_f1"]) for r in sub], marker=marker, linewidth=2, color=color, label=f"{label} — F1")
                ax2.plot(xs, [_pct(r["false_drop_rate"]) for r in sub], marker=marker, linewidth=1.2, linestyle="--", color=color, label=f"{label} — FDR")
        ax2.axvline(data.get("production_similarity", 80), color="#94A3B8", linestyle=":", linewidth=1.2)
        ax2.set_xlabel("Ngưỡng giống chữ (%) — chỉ để xem độ nhạy, không dùng chọn ngưỡng")
        ax2.set_ylabel("%")
        ax2.set_ylim(-5, 108)
        ax2.set_title("Độ nhạy theo ngưỡng giống chữ")
        ax2.legend(frameon=False, fontsize=7)
        fig.suptitle("Thí nghiệm 4B — Lọc tiếng vọng trên dữ liệu Online Meeting thật (nhãn gán mù)", fontsize=12, fontweight="bold")
        fig.tight_layout()
        p = charts_dir / "chart4b_echo_real.png"
        fig.savefig(p)
        plt.close(fig)
        saved.append(p)

    syn = data.get("synthetic_sensitivity") or []
    if syn:
        gains = sorted({r["gain_ratio"] for r in syn})
        show_gains = sorted({gains[0], gains[len(gains) // 2], gains[-1]})
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6))
        styles = ["-", "--", ":"]
        for mode, (label, color, marker) in _MODE_STYLE.items():
            for gi, gain in enumerate(show_gains):
                sub = sorted([r for r in syn if r["mode"] == mode and r["gain_ratio"] == gain], key=lambda r: r["echo_level"])
                if not sub:
                    continue
                xs = [r["echo_level"] * 100 for r in sub]
                ls = styles[gi % len(styles)]
                ax1.plot(xs, [_pct(r["echo_f1"]) for r in sub], marker=marker, linestyle=ls, color=color, label=f"{label}, mic lệch {gain:g}×")
                ax2.plot(xs, [_pct(r["false_drop_rate"]) for r in sub], marker=marker, linestyle=ls, color=color, label=f"{label}, mic lệch {gain:g}×")
        for ax, yl, title in ((ax1, "Echo F1 (%)", "Echo F1"), (ax2, "Bỏ nhầm câu thật (%)", "Tỉ lệ xóa nhầm câu của người nói thật")):
            ax.set_xlabel("Mức tiếng vọng (% giọng thường của mic nghe loa ngoài)")
            ax.set_ylabel(yl)
            ax.set_ylim(-5, 108)
            ax.set_title(title)
        ax1.legend(frameon=False, fontsize=7)
        fig.suptitle("Thí nghiệm 4B — Phân tích độ nhạy trên dữ liệu MÔ PHỎNG (minh họa, không phải số liệu chính)", fontsize=11, fontweight="bold")
        fig.tight_layout()
        p = charts_dir / "chart4c_echo_synthetic_sensitivity.png"
        fig.savefig(p)
        plt.close(fig)
        saved.append(p)
    return saved


def generate_all_charts(results_dir: Path, charts_dir: Path | None = None) -> list[Path]:
    _configure_style()
    charts_dir = charts_dir or (results_dir / "charts")
    charts_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    mapping = [
        ("exp1_stt.json", plot_exp1_stt),
        ("exp2_llm.json", plot_exp2_llm),
        ("exp3_e2e.json", plot_exp3_e2e),
        ("exp4_speakers.json", plot_exp4_speakers),
        ("exp4_echo.json", plot_exp4_echo),
    ]
    for fname, fn in mapping:
        fp = results_dir / fname
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
            generated.extend(fn(data, charts_dir))
    return generated


def main() -> None:
    ap = argparse.ArgumentParser(description="Vẽ biểu đồ 300 DPI từ kết quả thực nghiệm GĐ7")
    ap.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Thư mục chứa các file exp*.json")
    ap.add_argument("--charts-dir", help="Thư mục lưu ảnh PNG (mặc định <results-dir>/charts)")
    args = ap.parse_args()

    res_dir = Path(args.results_dir)
    out_dir = Path(args.charts_dir) if args.charts_dir else res_dir / "charts"
    files = generate_all_charts(res_dir, out_dir)
    if not files:
        print(f"Chưa tìm thấy file `exp*.json` nào trong {res_dir}. Hãy chạy exp1_stt.py / exp2_llm.py / exp4_online.py trước.")
    else:
        print(f"Đã vẽ {len(files)} biểu đồ 300 DPI:")
        for p in files:
            print(f"  - {p}")


if __name__ == "__main__":
    main()
