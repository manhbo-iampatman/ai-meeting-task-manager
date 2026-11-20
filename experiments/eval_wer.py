"""Tính WER (Word Error Rate — tỉ lệ lỗi từ) và CER của bản ghi so với đáp án chuẩn.

    WER = (S + D + I) / N
      S: số từ bị thay (nghe "bản" thay vì "bảng")
      D: số từ bị mất
      I: số từ bị chèn thừa
      N: tổng số từ của bản chuẩn

Báo cáo cả 2 cách tính cho minh bạch:
  - WER thô: so nguyên văn (chỉ bỏ dấu câu, chữ hoa).
  - WER chuẩn hóa số: đổi chữ số / ngày "25/11" / giờ "9h30" / "50%" / "2.000" sang chữ đọc chuẩn và
    quy các cách đọc tương đương (tư/bốn, mốt/một, lẻ/linh, nghìn/ngàn) ở CẢ HAI phía trước khi so,
    vì Whisper hay viết số bằng chữ số — về nghĩa thì KHÔNG sai.

Cách dùng:
  backend\\.venv\\Scripts\\python experiments\\eval_wer.py reference.txt hypothesis.txt
  backend\\.venv\\Scripts\\python experiments\\eval_wer.py --meeting 2 experiments/data/sample_meeting_01/reference.txt
  backend\\.venv\\Scripts\\python experiments\\eval_wer.py reference.txt hypothesis.txt --expected experiments/data/sample_meeting_01/expected_tasks.json
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jiwer  # noqa: E402
from common import (  # noqa: E402
    compute_wer_metrics,
    fmt_pct,
    load_meeting,
    normalize_for_wer,
    read_text,
    number_to_vi,  # giữ export cho các script khác nếu import từ eval_wer
)

__all__ = ["number_to_vi", "normalize", "evaluate"]


def normalize(text: str, numbers: bool) -> str:
    return normalize_for_wer(text, numbers=numbers)


def evaluate(ref: str, hyp: str, numbers: bool) -> jiwer.WordOutput:
    return jiwer.process_words(normalize(ref, numbers), normalize(hyp, numbers))


def show(title: str, o: jiwer.WordOutput) -> None:
    n = o.hits + o.substitutions + o.deletions
    print(f"{title}: WER = {o.wer * 100:.2f}%  (đúng {o.hits}, thay {o.substitutions}, mất {o.deletions}, thừa {o.insertions} / {n} từ)")
    for a in o.alignments[0]:
        if a.type != "equal":
            r = " ".join(o.references[0][a.ref_start_idx : a.ref_end_idx])
            h = " ".join(o.hypotheses[0][a.hyp_start_idx : a.hyp_end_idx])
            print(f"    {a.type:10s} chuẩn: '{r}'  →  nghe: '{h}'")


def fetch_meeting_text(meeting_id: int, base: str = "http://localhost:8000/api") -> str:
    """Lấy bản ghi từ API đang chạy (tài khoản demo của seed). Ghép NỘI DUNG từng câu, KHÔNG dùng
    `full_text` vì với Online Meeting `full_text` có tiền tố "Tên người nói:" → bị tính là từ chèn thừa."""
    import httpx

    tok = httpx.post(f"{base}/auth/login", json={"email": "nam@example.com", "password": "demo1234"}).json()["access_token"]
    d = httpx.get(f"{base}/meetings/{meeting_id}", headers={"Authorization": f"Bearer {tok}"}).json()
    segs = d["transcript"].get("segments") or []
    if segs:
        return "\n".join(str(s.get("text", "")).strip() for s in segs if str(s.get("text", "")).strip())
    return d["transcript"]["full_text"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Tính WER / CER của bản ghi STT so với đáp án chuẩn")
    ap.add_argument("reference", help="File bản ghi chuẩn (reference.txt)")
    ap.add_argument("hypothesis", nargs="?", help="File bản ghi cần chấm")
    ap.add_argument("--meeting", type=int, help="Lấy bản ghi từ cuộc họp id này trên API đang chạy")
    ap.add_argument("--expected", help="File expected_tasks.json (để đo thêm tỉ lệ nhận đúng tên thành viên)")
    a = ap.parse_args()

    if not a.meeting and not a.hypothesis:
        ap.error("Cần truyền file `hypothesis` hoặc `--meeting <id>`")

    ref_path = Path(a.reference)
    ref = read_text(ref_path)
    hyp = fetch_meeting_text(a.meeting) if a.meeting else read_text(Path(a.hypothesis))

    show("WER thô         ", evaluate(ref, hyp, numbers=False))
    print()
    show("WER chuẩn hóa số", evaluate(ref, hyp, numbers=True))

    members = None
    if a.expected:
        members = load_meeting(Path(a.expected).parent).members
    elif (ref_path.parent / "expected_tasks.json").exists():
        members = load_meeting(ref_path.parent).members

    m = compute_wer_metrics(ref, hyp, members=members)
    print(f"\nCER chuẩn hóa số : {fmt_pct(m.cer_norm, 2)}")
    if m.name_total > 0:
        print(f"Đúng tên thành viên: {m.name_hits}/{m.name_total} ({fmt_pct(m.name_accuracy, 1)})")


if __name__ == "__main__":
    main()
