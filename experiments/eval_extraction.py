"""Chấm điểm bước trích xuất đầu việc (Giai đoạn 4) so với đáp án chuẩn.

Với mỗi cuộc họp có sẵn đáp án (`expected_tasks.json`), chạy đúng pipeline của hệ thống
(LLM → ghép tên → tính ngày) rồi so sánh:

    Precision = số đầu việc AI tìm ĐÚNG / tổng số đầu việc AI đưa ra   (AI có bịa thêm không?)
    Recall    = số đầu việc AI tìm ĐÚNG / tổng số đầu việc trong đáp án (AI có bỏ sót không?)
    F1        = trung bình điều hòa của Precision và Recall
    Đúng người làm / đúng hạn chót: tính trên các đầu việc đã tìm đúng

Hai đầu việc được coi là "cùng một việc" khi nội dung giống nhau từ 60% trở lên
(so không dấu, không kể thứ tự từ).

Cách dùng (chạy từ thư mục gốc dự án, dùng .venv của backend):
  backend\\.venv\\Scripts\\python experiments\\eval_extraction.py
  backend\\.venv\\Scripts\\python experiments\\eval_extraction.py --model gemini-3.5-flash
  backend\\.venv\\Scripts\\python experiments\\eval_extraction.py --provider ollama --model qwen2.5:3b
  backend\\.venv\\Scripts\\python experiments\\eval_extraction.py --no-members          # thí nghiệm: bỏ danh sách thành viên khỏi prompt
  backend\\.venv\\Scripts\\python experiments\\eval_extraction.py --transcript ban_ghi_whisper.txt   # chấm trên bản ghi do Whisper sinh ra
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT / "backend")  # để đọc được backend/.env
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from rapidfuzz import fuzz  # noqa: E402

from app.ai.extraction import ExtractedItem, extract_meeting  # noqa: E402
from app.ai.llm.gemini_provider import GeminiProvider  # noqa: E402
from app.ai.llm.ollama_provider import OllamaProvider  # noqa: E402
from app.ai.postprocess.name_matching import MemberInfo  # noqa: E402
from app.ai.postprocess.text_utils import norm_no_accent  # noqa: E402
from app.core.config import get_settings  # noqa: E402

TITLE_THRESHOLD = 60


def build_llm(provider: str | None, model: str | None):
    s = get_settings()
    provider = provider or s.LLM_PROVIDER
    if provider == "gemini":
        return GeminiProvider(s.GEMINI_API_KEY, model or s.GEMINI_MODEL, s.LLM_TEMPERATURE, s.LLM_TIMEOUT_SEC)
    return OllamaProvider(s.OLLAMA_URL, model or s.OLLAMA_MODEL, s.OLLAMA_NUM_CTX, s.OLLAMA_KEEP_ALIVE, s.LLM_TEMPERATURE)


def match_tasks(expected: list[dict], predicted: list[ExtractedItem]) -> list[tuple[dict, ExtractedItem]]:
    """Ghép từng đầu việc đáp án với đầu việc AI giống nhất (mỗi đầu việc AI chỉ dùng 1 lần)."""
    scores = sorted(
        (
            (fuzz.token_set_ratio(norm_no_accent(e["task"]), norm_no_accent(p.title)), ei, pi)
            for ei, e in enumerate(expected)
            for pi, p in enumerate(predicted)
        ),
        reverse=True,
    )
    used_e: set[int] = set()
    used_p: set[int] = set()
    pairs = []
    for score, ei, pi in scores:
        if score < TITLE_THRESHOLD or ei in used_e or pi in used_p:
            continue
        used_e.add(ei)
        used_p.add(pi)
        pairs.append((expected[ei], predicted[pi]))
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(description="Chấm điểm trích xuất đầu việc")
    ap.add_argument("--data", default=str(ROOT / "experiments/data/sample_meeting_01"), help="thư mục có reference.txt + expected_tasks.json")
    ap.add_argument("--transcript", help="file bản ghi khác để chấm (vd. bản do Whisper sinh ra); mặc định dùng reference.txt")
    ap.add_argument("--provider", choices=["gemini", "ollama"])
    ap.add_argument("--model")
    ap.add_argument("--no-members", action="store_true", help="không đưa danh sách thành viên vào prompt")
    ap.add_argument("--out", help="lưu kết quả chi tiết ra file JSON")
    args = ap.parse_args()

    data = Path(args.data)
    answer = json.loads((data / "expected_tasks.json").read_text(encoding="utf-8"))
    expected: list[dict] = answer["tasks"]
    meeting_date = date.fromisoformat(answer["meeting_date"])
    text = Path(args.transcript or data / "reference.txt").read_text(encoding="utf-8")
    segments = [{"start": None, "end": None, "text": line.strip()} for line in text.splitlines() if line.strip()]

    # Thành viên nhóm = những người có tên trong đáp án
    names = sorted({t["assignee"] for t in expected if t.get("assignee")})
    members = [MemberInfo(i, name, []) for i, name in enumerate(names, 1)]
    name_of = {m.user_id: m.full_name for m in members}

    llm = build_llm(args.provider, args.model)
    print(f"Mô hình: {llm.name} | ngày họp {meeting_date} | {len(segments)} câu | thành viên: {', '.join(names)}")
    result = extract_meeting(llm, segments, meeting_date, members, include_members=not args.no_members)

    pairs = match_tasks(expected, result.items)
    tp = len(pairs)
    precision = tp / len(result.items) if result.items else 0.0
    recall = tp / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    who_ok = sum(1 for e, p in pairs if name_of.get(p.assignee_id) == e["assignee"])
    self_claimed = sum(1 for _, p in pairs if p.assignee_match == "self")
    due_ok = sum(1 for e, p in pairs if (p.due_date.isoformat() if p.due_date else None) == e.get("due_date"))
    evidence_ok = sum(1 for p in result.items if p.evidence_found)

    print("\nĐầu việc AI trích được:")
    for p in result.items:
        who = name_of.get(p.assignee_id) or f"(chưa ghép: {p.raw_assignee or '—'} / {p.assignee_match})"
        print(f"  - {p.title} | {who} | {p.due_date or '—'} ({p.due_text or 'không nói hạn'}) | câu gốc: {'có' if p.evidence_found else 'KHÔNG THẤY'}")
    missed = [e for e in expected if e not in [x for x, _ in pairs]]
    for e in missed:
        print(f"  ! BỎ SÓT: {e['task']} ({e['assignee']})")

    print("\nKết quả:")
    print(f"  Đáp án {len(expected)} đầu việc | AI đưa ra {len(result.items)} | khớp {tp}")
    print(f"  Precision {precision:.0%} | Recall {recall:.0%} | F1 {f1:.0%}")
    print(f"  Đúng người làm {who_ok}/{tp}" + (f" (trong đó {self_claimed} việc người nói tự nhận → hệ thống cố ý để trống)" if self_claimed else ""))
    print(f"  Đúng hạn chót {due_ok}/{tp}")
    print(f"  Câu gốc tìm thấy trong bản ghi {evidence_ok}/{len(result.items)}")
    print(f"  Thời gian {result.processing_sec:.1f} giây | {result.chunk_count} đoạn | token vào {result.input_tokens}, ra {result.output_tokens}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "model": result.llm_model,
                    "include_members": not args.no_members,
                    "precision": precision, "recall": recall, "f1": f1,
                    "assignee_correct": who_ok, "due_correct": due_ok, "matched": tp,
                    "self_claimed": self_claimed, "evidence_found": evidence_ok,
                    "processing_sec": result.processing_sec,
                    "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                    "summary": result.summary,
                    "items": [p.to_dict() for p in result.items],
                },
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nĐã lưu: {args.out}")


if __name__ == "__main__":
    main()
