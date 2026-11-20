"""THÍ NGHIỆM 2 & 3 (Giai đoạn 7) — So sánh LLM trích xuất đầu việc & đánh giá End-to-End.

- **Thí nghiệm 2 (LLM trên bản ghi chuẩn):** so sánh nhiều cấu hình LLM (VD. `gemini:gemini-3.5-flash`,
  `gemini:gemini-3.5-flash-lite`, `ollama:qwen2.5:3b`), temperature = 0, mỗi cấu hình chạy 1 lần.
  `--ablate-members` chạy thêm 2 nhánh:
    * `prompt_only` — bỏ danh sách thành viên + biệt danh KHỎI PROMPT (hậu xử lý vẫn ghép tên/biệt danh);
    * `none` — không có thành viên nào (`members=[]`): không prompt, không ghép tên ở hậu xử lý.
  → `results/exp2_llm.{json,csv,md}` (kèm bảng độ nhạy theo ngưỡng ghép tiêu đề 50/60/70/80).

- **Thí nghiệm 3 (End-to-End):** cùng LLM trên **bản ghi chuẩn** và **bản ghi do STT sinh ra**
  (`--stt-dirs`, từ `exp1_stt.py`). Bản chuẩn được tổng hợp lại trên ĐÚNG tập cuộc họp có bản STT rồi
  mới tính `ΔF1`, `ΔStrict F1`, `ΔĐúng người`, `ΔĐúng hạn` (kèm khoảng tin cậy bootstrap ghép cặp).
  → `results/exp3_e2e.{json,csv,md}`.

Lưu đệm (`--skip-existing`): chỉ lưu PHẢN HỒI THÔ của LLM trong `results/cache/`, khóa theo toàn bộ
tham số + nội dung bản ghi + `--run-id`; khi dùng lại, prompt được kiểm tra khớp và kết quả luôn được
CHẤM LẠI với đáp án hiện tại. Gemini hết hạn mức giữa chừng → chạy lại đúng lệnh để tiếp tục.

Ví dụ (PowerShell, 1 dòng):
  backend\\.venv\\Scripts\\python experiments\\exp2_llm.py --data experiments/data --models gemini:gemini-3.5-flash gemini:gemini-3.5-flash-lite ollama:qwen2.5:3b --ablate-members --sleep 2 --skip-existing
  backend\\.venv\\Scripts\\python experiments\\exp2_llm.py --data experiments/data --models gemini:gemini-3.5-flash --stt-dirs experiments/results/stt_transcripts/faster-whisper__large-v3-turbo__prompt --sleep 2 --skip-existing
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_DATA_DIR,
    DEFAULT_RESULTS_DIR,
    MeetingCase,
    discover_meetings,
    fmt_ci,
    fmt_pct,
    markdown_table,
    paired_bootstrap_delta,
    rnd,
    select_cases,
    warn_roster,
    write_csv,
    write_json,
    write_markdown,
)
from eval_extraction import (  # noqa: E402
    MEMBER_MODE_LABELS,
    SENSITIVITY_THRESHOLDS,
    aggregate_extraction_runs,
    build_llm,
    evaluate_cases_cached,
    stat_assignee_acc,
    stat_due_acc,
    stat_micro_f1,
    stat_strict_f1,
)


def parse_llm_spec(spec: str) -> tuple[str, str]:
    """`gemini:gemini-3.5-flash` → ('gemini', 'gemini-3.5-flash'); `ollama:qwen2.5:3b` → ('ollama', 'qwen2.5:3b')."""
    if ":" not in spec:
        raise ValueError(f"Cần ghi rõ `<provider>:<model>`, VD: `gemini:gemini-3.5-flash` hoặc `ollama:qwen2.5:3b` (nhận: {spec!r})")
    provider, model = spec.split(":", 1)
    if provider not in ("gemini", "ollama"):
        raise ValueError(f"Provider không hợp lệ `{provider}` (chỉ nhận `gemini` hoặc `ollama`)")
    return provider, model


def run_config_on_cases(
    *,
    label: str,
    provider: str,
    model: str,
    cases: list[MeetingCase],
    member_mode: str = "full",
    transcript_dir: Path | None = None,
    cache_dir: Path,
    skip_existing: bool,
    sleep_sec: float,
    allow_fallback: bool,
    run_id: str = "r1",
    extra_meta: dict[str, Any] | None = None,
    llm_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Chạy 1 cấu hình (LLM × nhánh thành viên × nguồn bản ghi) trên các cuộc họp rồi tổng hợp."""
    factory = llm_factory or (lambda: build_llm(provider, model, allow_fallback=allow_fallback))
    print(f"\n=== [{label}] ({len(cases)} cuộc họp) ===")

    def show(c: MeetingCase, row: dict[str, Any]) -> None:
        tag = " (cache)" if row.get("from_cache") else ""
        if row.get("failed"):
            print(f"  [{c.meeting_id}]{tag} THẤT BẠI (tính mọi đầu việc là FN): {row['error']}")
            return
        print(
            f"  [{c.meeting_id}]{tag} P={fmt_pct(row['precision'])} R={fmt_pct(row['recall'])} F1={fmt_pct(row['f1'])} "
            f"Strict={fmt_pct(row['strict_f1'])} | Người {row['assignee_correct']}/{row['tp']} | Hạn {row['due_correct']}/{row['tp']} | "
            f"{row['chunk_count']} đoạn | {row['processing_sec']:.1f}s"
        )

    rows = evaluate_cases_cached(
        cases=cases,
        llm_factory=factory,
        provider=provider,
        model=model,
        member_mode=member_mode,
        use_speakers=False,
        transcript_dir=transcript_dir,
        cache_dir=cache_dir,
        skip_existing=skip_existing,
        run_id=run_id,
        allow_fallback=allow_fallback,
        sleep_sec=sleep_sec if provider == "gemini" else 0.0,
        on_row=show,
    )
    meta = {
        "provider": provider,
        "model": f"{provider}/{model}",
        "member_mode": member_mode,
        "include_members": member_mode == "full",
        "allow_fallback": allow_fallback,
        "run_id": run_id,
        "transcript_type": "stt" if transcript_dir else "reference",
        "transcript_dir": str(transcript_dir) if transcript_dir else None,
        **(extra_meta or {}),
    }
    return aggregate_extraction_runs(label, rows, meta=meta)


def restrict_run(run: dict[str, Any], meeting_ids: set[str], label: str | None = None) -> dict[str, Any]:
    """Tổng hợp lại một lần chạy trên ĐÚNG tập cuộc họp cho trước (để so sánh công bằng)."""
    rows = [r for r in run["per_meeting"] if r["meeting_id"] in meeting_ids]
    meta = {k: v for k, v in run.items() if k in ("provider", "model", "member_mode", "include_members", "allow_fallback", "run_id", "transcript_type")}
    return aggregate_extraction_runs(label or run["label"], rows, meta=meta)


def e2e_deltas(gold: dict[str, Any], stt: dict[str, Any]) -> dict[str, Any]:
    """Δ (STT − bản chuẩn) trên cùng tập cuộc họp, kèm khoảng tin cậy bootstrap ghép cặp."""
    out: dict[str, Any] = {}
    for key, fn in (("f1", stat_micro_f1), ("strict_f1", stat_strict_f1), ("assignee_acc", stat_assignee_acc), ("due_acc", stat_due_acc)):
        out[key] = paired_bootstrap_delta(gold["per_meeting"], stt["per_meeting"], fn)
    return out


def _cell_pct_ci(r: dict[str, Any], key: str) -> str:
    return f"{fmt_pct(r.get(key))}{fmt_ci(r.get(key + '_ci95'))}"


def _extraction_table(runs: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    headers = [
        "Cấu hình",
        "Số cuộc (lỗi)",
        "TP / FP / FN",
        "Micro P",
        "Micro R",
        "Micro F1 [95% CI]",
        "Macro F1",
        "Strict F1 [95% CI]",
        "Đúng người (bỏ trống / sai)",
        "Đúng hạn (việc có hạn)",
        "Bịa hạn",
        "Thấy câu gốc",
        "Đoạn LLM (TB / max)",
        "TB thời gian",
        "Token (vào/ra)",
    ]
    rows: list[list[Any]] = []
    for r in runs:
        rows.append(
            [
                r["label"],
                f"{r['meetings_count']} ({len(r.get('failed_meetings') or [])})",
                f"{r['tp']} / {r['fp']} / {r['fn']}",
                fmt_pct(r["micro_precision"]),
                fmt_pct(r["micro_recall"]),
                _cell_pct_ci(r, "micro_f1"),
                fmt_pct(r["macro_f1"]),
                _cell_pct_ci(r, "strict_f1"),
                f"{r['assignee_correct']}/{r['tp']} ({fmt_pct(r['assignee_acc'])}; {r['assignee_blank']} / {r['assignee_wrong']})",
                f"{r['due_with_date_correct']}/{r['due_with_date_total']} ({fmt_pct(r['due_with_date_acc'])})",
                f"{r['spurious_due']}/{r['gold_no_due_matched']} ({fmt_pct(r['spurious_due_rate'])})",
                f"{r['evidence_found']}/{r['predicted_total']} ({fmt_pct(r['evidence_rate'])})",
                f"{r['chunk_count_avg'] if r['chunk_count_avg'] is not None else '—'} / {r['chunk_count_max'] if r['chunk_count_max'] is not None else '—'}",
                f"{r['avg_processing_sec']:.1f}s" if r["avg_processing_sec"] is not None else "—",
                f"{r['input_tokens']}/{r['output_tokens']}",
            ]
        )
    return headers, rows


def _sensitivity_table(runs: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    headers = ["Cấu hình", *[f"F1 @ ngưỡng {th}" for th in SENSITIVITY_THRESHOLDS]]
    rows = [[r["label"], *[fmt_pct(r["threshold_sensitivity"][str(th)]["f1"]) for th in SENSITIVITY_THRESHOLDS]] for r in runs]
    return headers, rows


def _error_summary_markdown(runs: list[dict[str, Any]]) -> str:
    """Tóm tắt nhanh các lỗi phổ biến (bỏ sót, bịa thêm, sai người, sai hạn) để phân tích ở Chương 4."""
    lines: list[str] = []
    for r in runs:
        missed = [(m["meeting_id"], t["task"]) for m in r["per_meeting"] for t in m["missed_tasks"]]
        extra = [(m["meeting_id"], t["title"]) for m in r["per_meeting"] for t in m["extra_tasks"]]
        who_err = [(m["meeting_id"], e) for m in r["per_meeting"] for e in m["assignee_errors"]]
        due_err = [(m["meeting_id"], e) for m in r["per_meeting"] for e in m["due_errors"]]
        lines.append(f"### `{r['label']}`")
        lines.append(
            f"- Bỏ sót (FN): **{len(missed)}** | Bịa / dư (FP): **{len(extra)}** | "
            f"Sai người làm: **{len(who_err)}** (bỏ trống {r['assignee_blank']}, sai người {r['assignee_wrong']}) | Sai hạn: **{len(due_err)}**"
        )
        if r.get("failed_meetings"):
            lines.append(f"- Cuộc họp LLM trả kết quả hỏng (tính toàn bộ là FN): {', '.join(r['failed_meetings'])}")
        for mid, task in missed[:5]:
            lines.append(f"  - Bỏ sót `[{mid}]`: {task}")
        for mid, title in extra[:5]:
            lines.append(f"  - Dư/bịa `[{mid}]`: {title}")
        for mid, e in who_err[:5]:
            lines.append(
                f"  - Sai người `[{mid}]` ({e['error_type']}): *{e['task']}* — chuẩn `{e['expected_assignee']}` vs AI `{e['predicted_assignee']}` ({e['assignee_match']})"
            )
        for mid, e in due_err[:5]:
            lines.append(f"  - Sai hạn `[{mid}]`: *{e['task']}* — chuẩn `{e['expected_due']}` vs AI `{e['predicted_due']}` (`{e['due_text']}`)")
        lines.append("")
    return "\n".join(lines)


_EXP2_NOTES = """- Temperature = 0, mỗi cấu hình chạy 1 lần; khoảng tin cậy 95% = bootstrap 2000 lần theo cuộc họp (hạt giống cố định).
- **Micro F1** chỉ xét khớp tiêu đề; **Strict F1** chỉ tính đầu việc khớp tiêu đề + đúng người + đúng hạn.
- "Đúng người" và "Đúng hạn" tính trên các cặp đã khớp (mỗi cấu hình một tập khác nhau) → so sánh giữa cấu hình nên dựa vào Strict F1.
- Nhánh `(bỏ DS thành viên khỏi prompt)` chỉ bỏ danh sách khỏi prompt, hậu xử lý VẪN ghép tên/biệt danh; nhánh `(không có thành viên)` truyền `members=[]` nên không có ghép tên — người làm được chấm theo chữ AI viết (họ tên hoặc tên gọi thật, biệt danh không tính).
- Macro F1 chỉ tính trên các cuộc họp có ít nhất 1 đầu việc trong đáp án. Ô "—" = không định nghĩa (mẫu số 0).
- Cuộc họp mà LLM trả kết quả hỏng (JSON sai cấu trúc) được tính là thất bại (mọi đầu việc là FN), không bị loại khỏi mẫu."""


def export_exp2_reports(runs: list[dict[str, Any]], out_dir: Path) -> None:
    write_json(out_dir / "exp2_llm.json", {"experiment": "exp2_llm", "runs": runs})
    h, rows = _extraction_table(runs)
    write_csv(out_dir / "exp2_llm.csv", h, rows)
    sh, srows = _sensitivity_table(runs)
    write_markdown(
        out_dir / "exp2_llm.md",
        "Kết quả Thí nghiệm 2 — So sánh LLM trích xuất đầu việc (trên bản ghi chuẩn)",
        [
            ("Bảng tổng hợp", markdown_table(h, rows)),
            ("Ghi chú phương pháp", _EXP2_NOTES),
            ("Độ nhạy theo ngưỡng ghép tiêu đề (Micro F1)", markdown_table(sh, srows)),
            ("Phân tích lỗi chi tiết", _error_summary_markdown(runs)),
        ],
    )


def _delta_cell(d: dict[str, Any]) -> str:
    if d.get("delta") is None:
        return "—"
    ci = d.get("ci95")
    ci_s = f" [{ci[0] * 100:+.1f}; {ci[1] * 100:+.1f}]" if ci else ""
    return f"{d['delta'] * 100:+.1f} đ%{ci_s}"


def export_exp3_reports(groups: list[dict[str, Any]], out_dir: Path) -> None:
    write_json(out_dir / "exp3_e2e.json", {"experiment": "exp3_e2e", "groups": groups})
    headers = [
        "LLM",
        "Nguồn bản ghi",
        "Số cuộc",
        "Micro F1 [95% CI]",
        "Strict F1 [95% CI]",
        "Đúng người",
        "Đúng hạn",
        "ΔF1 [95% CI]",
        "ΔStrict F1",
        "ΔĐúng người",
        "ΔĐúng hạn",
    ]
    all_rows: list[list[Any]] = []
    sections: list[tuple[str, str]] = []
    for g in groups:
        rows: list[list[Any]] = []
        for comp in g["comparisons"]:
            gold, stt, d = comp["gold"], comp["stt"], comp["deltas"]
            for name, r, deltas in (("Bản chuẩn", gold, None), (f"STT ({comp['stt_source']})", stt, d)):
                rows.append(
                    [
                        g["llm"],
                        name,
                        r["meetings_count"],
                        _cell_pct_ci(r, "micro_f1"),
                        _cell_pct_ci(r, "strict_f1"),
                        fmt_pct(r["assignee_acc"]),
                        fmt_pct(r["due_acc"]),
                        *(["gốc"] * 4 if deltas is None else [_delta_cell(deltas[k]) for k in ("f1", "strict_f1", "assignee_acc", "due_acc")]),
                    ]
                )
        all_rows.extend(rows)
        sections.append((f"LLM: `{g['llm']}` — Bản ghi chuẩn vs Bản ghi STT (cùng tập cuộc họp)", markdown_table(headers, rows)))
    sections.append(
        (
            "Ghi chú phương pháp",
            "- Mỗi dòng 'Bản chuẩn' được tổng hợp lại trên ĐÚNG tập cuộc họp có bản ghi STT tương ứng.\n"
            "- Δ = STT − bản chuẩn (điểm %), khoảng tin cậy 95% = bootstrap ghép cặp theo cuộc họp.\n"
            "- 'Đúng người' / 'Đúng hạn' tính trên các cặp đã khớp; Strict F1 là chỉ số end-to-end.",
        )
    )
    write_csv(out_dir / "exp3_e2e.csv", headers, all_rows)
    write_markdown(out_dir / "exp3_e2e.md", "Kết quả Thí nghiệm 3 — End-to-End (lan truyền lỗi STT → LLM)", sections)


def main() -> None:
    ap = argparse.ArgumentParser(description="Thí nghiệm 2 & 3 (GĐ7): So sánh LLM & đánh giá End-to-End")
    ap.add_argument("--data", default=str(DEFAULT_DATA_DIR), help="Thư mục dữ liệu (1 hoặc nhiều cuộc họp)")
    ap.add_argument(
        "--models",
        nargs="+",
        default=["gemini:gemini-3.5-flash", "gemini:gemini-3.5-flash-lite"],
        help="Danh sách `<provider>:<model>`, VD: gemini:gemini-3.5-flash ollama:qwen2.5:3b",
    )
    ap.add_argument("--ablate-members", action="store_true", help="Chạy thêm 2 nhánh: bỏ DS thành viên khỏi prompt, và không có thành viên (members=[])")
    ap.add_argument("--stt-dirs", nargs="*", default=[], help="Thư mục bản ghi do STT sinh ra (từ exp1_stt.py) cho Thí nghiệm 3")
    ap.add_argument("--allow-fallback", action="store_true", help="Cho phép Gemini tự chuyển sang mô hình dự phòng")
    ap.add_argument("--skip-existing", action="store_true", help="Dùng lại phản hồi thô đã lưu (vẫn chấm lại với đáp án hiện tại)")
    ap.add_argument("--run-id", default="r1", help="Nhãn lần chạy (khóa cache). Đổi nhãn để chạy lại độc lập")
    ap.add_argument("--include-synthetic", action="store_true", help="Tính cả cuộc họp giả lập (synthetic: true)")
    ap.add_argument("--sleep", type=float, default=1.5, help="Nghỉ giữa các lần gọi Gemini thật (giây)")
    ap.add_argument("--out-dir", default=str(DEFAULT_RESULTS_DIR))
    args = ap.parse_args()

    cases = select_cases([c for c in discover_meetings(Path(args.data)) if c.has_expected_tasks], args.include_synthetic)
    cases = [c for c in cases if c.has_reference or c.has_speaker_reference]
    if not cases:
        raise SystemExit(f"Không tìm thấy cuộc họp nào có `expected_tasks.json` (đã gán nhãn) + bản ghi chuẩn trong {args.data}")
    warn_roster(cases)

    out_dir = Path(args.out_dir)
    cache_dir = out_dir / "cache"
    common_kw = {"cache_dir": cache_dir, "skip_existing": args.skip_existing, "sleep_sec": args.sleep, "allow_fallback": args.allow_fallback, "run_id": args.run_id}

    # --- TN2: bản ghi chuẩn ---
    exp2_runs: list[dict[str, Any]] = []
    gold_by_model: dict[str, dict[str, Any]] = {}
    modes = ["full", "prompt_only", "none"] if args.ablate_members else ["full"]
    for spec in args.models:
        provider, model = parse_llm_spec(spec)
        for mode in modes:
            run = run_config_on_cases(
                label=f"{provider}/{model}{MEMBER_MODE_LABELS[mode]}",
                provider=provider,
                model=model,
                cases=cases,
                member_mode=mode,
                **common_kw,
            )
            exp2_runs.append(run)
            if mode == "full":
                gold_by_model[spec] = run

    export_exp2_reports(exp2_runs, out_dir)
    print(f"\nĐã xuất kết quả TN2 tại: {out_dir / 'exp2_llm.md'} | {out_dir / 'exp2_llm.csv'} | {out_dir / 'exp2_llm.json'}")

    # --- TN3: End-to-End (bản ghi STT vs bản ghi chuẩn, cùng tập cuộc họp) ---
    if args.stt_dirs:
        groups: list[dict[str, Any]] = []
        for spec in args.models:
            provider, model = parse_llm_spec(spec)
            gold = gold_by_model[spec]
            comparisons: list[dict[str, Any]] = []
            for raw_dir in args.stt_dirs:
                sdir = Path(raw_dir)
                if not sdir.is_dir():
                    print(f"Cảnh báo: không tìm thấy thư mục STT `{sdir}`, bỏ qua.")
                    continue
                matched = [c for c in cases if (sdir / f"{c.meeting_id}.json").exists() or (sdir / f"{c.meeting_id}.txt").exists()]
                if not matched:
                    print(f"Cảnh báo: không có bản ghi khớp trong `{sdir}`.")
                    continue
                if len(matched) < len(cases):
                    print(f"  (TN3) `{sdir.name}` có {len(matched)}/{len(cases)} cuộc họp → bản chuẩn được tổng hợp lại trên đúng {len(matched)} cuộc này.")
                stt = run_config_on_cases(
                    label=f"{provider}/{model} + STT({sdir.name})",
                    provider=provider,
                    model=model,
                    cases=matched,
                    member_mode="full",
                    transcript_dir=sdir,
                    extra_meta={"stt_source": sdir.name},
                    **common_kw,
                )
                ids = {c.meeting_id for c in matched}
                gold_same = restrict_run(gold, ids, label=f"{provider}/{model} (bản chuẩn, {len(ids)} cuộc)")
                comparisons.append({"stt_source": sdir.name, "gold": gold_same, "stt": stt, "deltas": e2e_deltas(gold_same, stt)})
            if comparisons:
                groups.append({"llm": f"{provider}/{model}", "comparisons": comparisons})
        if groups:
            export_exp3_reports(groups, out_dir)
            print(f"Đã xuất kết quả TN3 tại: {out_dir / 'exp3_e2e.md'} | {out_dir / 'exp3_e2e.csv'} | {out_dir / 'exp3_e2e.json'}")
            for g in groups:
                for comp in g["comparisons"]:
                    d = comp["deltas"]["f1"]
                    print(f"  {g['llm']} + {comp['stt_source']}: ΔF1 = {rnd(d['delta'])} CI {d['ci95']}")


if __name__ == "__main__":
    main()
