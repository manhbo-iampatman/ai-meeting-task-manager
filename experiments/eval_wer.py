"""Tính WER (Word Error Rate — tỉ lệ lỗi từ) của bản ghi so với đáp án chuẩn.

    WER = (S + D + I) / N
      S: số từ bị thay (nghe "bản" thay vì "bảng")
      D: số từ bị mất
      I: số từ bị chèn thừa
      N: tổng số từ của bản chuẩn

Có 2 cách tính:
  - WER thô: so nguyên văn (chỉ bỏ dấu câu, chữ hoa).
  - WER chuẩn hóa: đổi chữ số thành chữ ("25" → "hai mươi lăm") trước khi so,
    vì Whisper hay viết số bằng chữ số — về nghĩa thì KHÔNG sai.
  → Báo cáo cả 2 cho minh bạch.

Cách dùng:
  python experiments/eval_wer.py reference.txt hypothesis.txt
  python experiments/eval_wer.py --meeting 2 experiments/data/sample_meeting_01/reference.txt
     (lấy bản ghi của cuộc họp id=2 từ API đang chạy, đăng nhập bằng tài khoản demo)
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import jiwer

sys.stdout.reconfigure(encoding="utf-8")

DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def number_to_vi(n: int) -> str:
    """Đọc số 0–999 theo tiếng Việt (đủ cho ngày, giờ, số lượng trong cuộc họp)."""
    if n < 10:
        return DIGITS[n]
    if n < 20:
        u = n % 10
        return "mười" + ("" if u == 0 else " lăm" if u == 5 else " " + DIGITS[u])
    if n < 100:
        t, u = divmod(n, 10)
        tail = "" if u == 0 else " mốt" if u == 1 else " tư" if u == 4 else " lăm" if u == 5 else " " + DIGITS[u]
        return f"{DIGITS[t]} mươi{tail}"
    if n < 1000:
        h, r = divmod(n, 100)
        if r == 0:
            return f"{DIGITS[h]} trăm"
        if r < 10:
            return f"{DIGITS[h]} trăm lẻ {DIGITS[r]}"
        return f"{DIGITS[h]} trăm {number_to_vi(r)}"
    return str(n)


def normalize(text: str, numbers: bool) -> str:
    t = unicodedata.normalize("NFC", text.lower())
    t = re.sub(r"[^\w\s]", " ", t)
    if numbers:
        t = re.sub(r"\d+", lambda m: number_to_vi(int(m.group())), t)
        # "thứ tư" hay được đọc là "thứ bốn" khi chuyển ngược → quy về "tư"
        t = re.sub(r"\bthứ bốn\b", "thứ tư", t)
    return re.sub(r"\s+", " ", t).strip()


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


def fetch_meeting_text(meeting_id: int) -> str:
    import httpx

    base = "http://localhost:8000/api"
    tok = httpx.post(f"{base}/auth/login", json={"email": "nam@example.com", "password": "demo1234"}).json()["access_token"]
    d = httpx.get(f"{base}/meetings/{meeting_id}", headers={"Authorization": f"Bearer {tok}"}).json()
    return d["transcript"]["full_text"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reference")
    ap.add_argument("hypothesis", nargs="?")
    ap.add_argument("--meeting", type=int, help="lấy bản ghi từ cuộc họp id này (API phải đang chạy)")
    a = ap.parse_args()

    ref = Path(a.reference).read_text(encoding="utf-8")
    hyp = fetch_meeting_text(a.meeting) if a.meeting else Path(a.hypothesis).read_text(encoding="utf-8")
    show("WER thô        ", evaluate(ref, hyp, numbers=False))
    print()
    show("WER chuẩn hóa số", evaluate(ref, hyp, numbers=True))


if __name__ == "__main__":
    main()
