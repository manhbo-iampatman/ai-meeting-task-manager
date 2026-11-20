"""Pipeline Giai đoạn 4: bản ghi → biên bản + danh sách đầu việc.

    bản ghi ──► [chia đoạn nếu dài] ──► LLM (JSON theo schema) ──► kiểm tra dữ liệu
            ──► hậu xử lý bằng code: tách người, ghép tài khoản, tính ngày, tìm câu gốc

File này KHÔNG đụng tới CSDL hay hàng đợi: nhận dữ liệu vào, trả kết quả ra. Nhờ vậy
dùng lại được ở 2 nơi — worker (app/workers/jobs.py) và script chấm điểm thực nghiệm
(experiments/eval_extraction.py) — và test được bằng một LLM giả.
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator
from rapidfuzz import fuzz

from app.ai.llm.base import LLMError, LLMProvider
from app.ai.llm.chunking import chunk_lines
from app.ai.llm.prompts import (
    EXTRACTION_SCHEMA,
    REDUCE_SYSTEM_PROMPT,
    SUMMARY_SCHEMA,
    SYSTEM_PROMPT,
    build_reduce_prompt,
    build_user_prompt,
)
from app.ai.postprocess.name_matching import MemberInfo, NameMatch, match_name, split_assignees, strip_honorific
from app.ai.postprocess.text_utils import norm, norm_no_accent
from app.ai.postprocess.vi_date_parser import parse_due

log = logging.getLogger(__name__)

EVIDENCE_THRESHOLD = 85  # câu trích dẫn giống câu trong bản ghi từ 85% trở lên thì coi là "tìm thấy"
DUPLICATE_THRESHOLD = 88  # hai đầu việc giống nhau từ 88% (cùng người làm) thì coi là trùng


# ---------- Kiểm tra dữ liệu LLM trả về (không tin tuyệt đối vào schema) ----------


def _clean_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    return [str(x).strip() for x in v if x is not None and str(x).strip()]


class LLMSummary(BaseModel):
    topic: str = ""
    key_points: list[str] = []
    decisions: list[str] = []
    open_issues: list[str] = []

    @field_validator("topic", mode="before")
    @classmethod
    def _topic(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()

    @field_validator("key_points", "decisions", "open_issues", mode="before")
    @classmethod
    def _lists(cls, v: Any) -> list[str]:
        return _clean_list(v)


class LLMActionItem(BaseModel):
    task: str
    assignees: list[str] = []
    due: str = ""
    priority: str = "medium"
    evidence: str = ""

    @field_validator("task", "due", "evidence", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()

    @field_validator("assignees", mode="before")
    @classmethod
    def _assignees(cls, v: Any) -> list[str]:
        return _clean_list(v)

    @field_validator("priority", mode="before")
    @classmethod
    def _priority(cls, v: Any) -> str:
        v = str(v or "").strip().lower()
        return v if v in ("low", "medium", "high") else "medium"


class LLMOutput(BaseModel):
    summary: LLMSummary = LLMSummary()
    action_items: list[LLMActionItem] = []


# ---------- Kết quả trả ra ----------


@dataclass
class ExtractedItem:
    title: str
    raw_assignee: str | None  # chữ LLM nghe được: "Nam", "anh", "Duy"...
    assignee_id: int | None  # tài khoản ghép được (None = chưa ghép)
    assignee_match: str  # exact | no_accent | fuzzy | ambiguous | self | group | none | speaker
    assignee_score: int
    assignee_candidates: list[int]
    due_text: str | None  # nguyên văn: "thứ Sáu tuần này"
    due_date: date | None  # ngày đã tính
    due_approximate: bool  # True = ước lượng theo quy ước, cần người dùng kiểm tra
    priority: str
    evidence_quote: str
    evidence_found: bool  # câu trích dẫn có thật trong bản ghi không
    evidence_segment: int | None  # vị trí câu trong bản ghi
    evidence_start: float | None  # giây — để bấm vào là nghe lại đúng câu đó

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["due_date"] = self.due_date.isoformat() if self.due_date else None
        return d


@dataclass
class ExtractionResult:
    summary: dict[str, Any]
    items: list[ExtractedItem]
    llm_model: str
    chunk_count: int
    processing_sec: float
    input_tokens: int = 0
    output_tokens: int = 0
    fallback_from: str | None = None  # mô hình chính bị bỏ qua (quá tải) → kết quả do mô hình dự phòng viết


# ---------- Tìm câu trích dẫn trong bản ghi ----------


def quote_speakers(quote: str, segments: list[dict[str, Any]], around: int | None, window: float = 8.0) -> set[Any]:
    """Những người nói có câu (đủ dài) nằm TRỌN trong câu trích dẫn, quanh vị trí `around`.

    LLM đôi khi chép gộp câu hỏi của người này với câu nhận việc của người kia ("Phần slide
    thì ai nhận? Để em làm ạ."). Khi đó từng câu riêng đều khớp một phần 100% → không biết
    chắc câu bằng chứng là của ai → KHÔNG được dùng nhãn người nói để gán việc.
    """
    if around is None:
        return set()
    q = norm_no_accent(quote)
    t0 = segments[around].get("start")
    out: set[Any] = set()
    for s in segments:
        c = norm_no_accent(str(s.get("text", "")))
        if len(c) < 12 or s.get("speaker_id") is None:
            continue
        st = s.get("start")
        if t0 is not None and st is not None and abs(float(st) - float(t0)) > window:
            continue
        if fuzz.partial_ratio(c, q) >= 95 and len(c) < len(q):
            out.add(s.get("speaker_id"))
    out.add(segments[around].get("speaker_id"))
    out.discard(None)
    return out


def find_evidence(quote: str, segments: list[dict[str, Any]]) -> tuple[int | None, int]:
    """Tìm câu trong bản ghi giống `quote` nhất → (vị trí câu, điểm 0–100).

    Đây là lớp kiểm tra "AI có bịa không": LLM bị yêu cầu chép nguyên văn câu làm bằng
    chứng; nếu câu đó KHÔNG có trong bản ghi thì đầu việc bị gắn cảnh báo.
    So sánh không dấu, không phân biệt hoa thường. Thử cả cặp 2 câu liền nhau vì Whisper
    có thể cắt một câu nói thành 2 dòng.
    """
    q = norm_no_accent(quote)
    if not q:
        return None, 0
    texts = [norm_no_accent(str(s.get("text", ""))) for s in segments]

    def similarity(c: str) -> int:
        score = fuzz.ratio(q, c)
        # Trích dẫn là MỘT PHẦN của câu dài (hoặc ngược lại) vẫn hợp lệ, nhưng chỉ chấp nhận
        # khi đủ dài — chuỗi quá ngắn ("vâng ạ") thì ở đâu cũng "khớp".
        if min(len(q), len(c)) >= 12:
            score = max(score, fuzz.partial_ratio(q, c))
        return int(score)

    def best_of(candidates: list[str]) -> tuple[int | None, int]:
        best_i, best = None, 0
        for i, c in enumerate(candidates):
            if c and (score := similarity(c)) > best:
                best_i, best = i, score
        return best_i, best

    # Ưu tiên khớp với ĐÚNG MỘT câu (để mốc thời gian chỉ đúng câu đó)...
    found = best_of(texts)
    if found[1] >= EVIDENCE_THRESHOLD:
        return found
    # ...không được thì mới thử ghép 2 câu liền nhau (chỉ ghép khi CÙNG người nói để tránh
    # gán nhầm `said_by` sang người nói câu trước trong Online Meeting). Lưu ý: vì đã so khớp
    # MỘT PHẦN ở trên nên bước này hiếm khi cần; trường hợp LLM chép gộp lời của 2 người do
    # `quote_speakers` xử lý.
    def same_speaker(i: int, j: int) -> bool:
        a, b = segments[i], segments[j]
        return a.get("speaker_id") == b.get("speaker_id") and a.get("speaker") == b.get("speaker")

    pairs = [
        f"{texts[i]} {texts[i + 1]}" if texts[i] and texts[i + 1] and same_speaker(i, i + 1) else ""
        for i in range(len(texts) - 1)
    ]
    paired = best_of(pairs)
    return paired if paired[1] > found[1] else found


# ---------- Bản ghi có tên người nói (Online Meeting, Giai đoạn 6) ----------


def speaker_labels(segments: list[dict[str, Any]]) -> dict[str, int]:
    """Nhãn người nói xuất hiện trong bản ghi → id tài khoản: {"nguyễn văn nam": 3, ...}.

    Chỉ cuộc họp Online Meeting mới có: mỗi người ghi bằng mic của mình nên hệ thống biết
    chắc câu nào của ai. Bản ghi từ file ghi âm thường → dict rỗng.
    """
    out: dict[str, int] = {}
    for s in segments:
        label, uid = s.get("speaker"), s.get("speaker_id")
        if label and uid is not None:
            out[norm(str(label))] = int(uid)
    return out


def transcript_lines(segments: list[dict[str, Any]], with_speakers: bool = True) -> list[str]:
    """Các dòng đưa cho LLM đọc. Có nhãn người nói thì mỗi dòng là "Họ Tên: câu nói"."""
    lines = []
    for s in segments:
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        speaker = s.get("speaker") if with_speakers else None
        lines.append(f"{speaker}: {text}" if speaker else text)
    return lines


def _strip_speaker(quote: str, speakers: dict[str, int]) -> str:
    """LLM lỡ chép cả "Nguyễn Văn Nam: " vào câu trích dẫn → bỏ phần tên trước khi đi tìm câu gốc."""
    head, sep, rest = quote.partition(":")
    if sep and rest.strip() and norm(head) in speakers:
        return rest.strip()
    return quote


# ---------- Hậu xử lý ----------


def _postprocess(
    raw_items: list[LLMActionItem],
    segments: list[dict[str, Any]],
    meeting_date: date,
    members: list[MemberInfo],
    speakers: dict[str, int] | None = None,
) -> list[ExtractedItem]:
    speakers = speakers or {}
    out: list[ExtractedItem] = []
    for it in raw_items:
        if not it.task:
            continue
        # Một việc giao cho nhiều người → tách thành mỗi người một đầu việc
        names = [n for a in it.assignees for n in split_assignees(a)] or [None]
        due = parse_due(it.due, meeting_date)
        evidence = _strip_speaker(it.evidence, speakers)
        seg_i, score = find_evidence(evidence, segments)
        found = score >= EVIDENCE_THRESHOLD
        start = segments[seg_i].get("start") if found and seg_i is not None else None
        # Online Meeting: ai là người NÓI câu bằng chứng (biết chắc, vì mỗi người ghi bằng mic của mình).
        # Câu trích dẫn gộp lời của 2 người trở lên → không biết chắc → không dùng nhãn người nói.
        said_by = segments[seg_i].get("speaker_id") if speakers and found and seg_i is not None else None
        if said_by is not None and len(quote_speakers(evidence, segments, seg_i)) > 1:
            said_by = None
        for name in names:
            # LLM chép đúng nhãn người nói ở đầu dòng → biết chắc tài khoản, không cần so khớp mờ.
            # Còn lại ghép tên như GĐ4.
            label_id = speakers.get(norm(name)) if name else None
            m = NameMatch(label_id, "exact", 100) if label_id is not None else match_name(name, members)
            # Người làm chính là người nói câu đó → NGƯỜI NÓI TỰ NHẬN VIỆC ("để em làm", "anh lo phần này").
            # Nhóm có 2 bạn trùng tên (ambiguous) mà một trong hai là người nói → chọn đúng người nói.
            if said_by is not None and (m.user_id == said_by or (m.method == "ambiguous" and said_by in m.candidates)):
                m = NameMatch(said_by, "speaker", 100)
            out.append(
                ExtractedItem(
                    title=it.task[:255],
                    raw_assignee=name[:100] if name else None,
                    assignee_id=m.user_id,
                    assignee_match=m.method,
                    assignee_score=m.score,
                    assignee_candidates=m.candidates,
                    due_text=it.due[:200] or None,
                    due_date=due.date,
                    due_approximate=due.approximate,
                    priority=it.priority,
                    evidence_quote=evidence,
                    evidence_found=found,
                    evidence_segment=seg_i if found else None,
                    evidence_start=float(start) if start is not None else None,
                )
            )
    return _dedupe(out)


def same_task(a: str, b: str) -> bool:
    """Hai tiêu đề có phải cùng một việc không.

    - So theo TẬP TỪ (token_set_ratio): "Viết chương 2" là bản rút gọn của "Viết chương 2,
      phần cơ sở lý thuyết" → trùng. Đây đúng là kiểu trùng gặp khi chạy thật: cuối họp
      chủ trì nhắc lại ngắn gọn ("chốt lại: Lan viết chương 2").
    - Nhưng con số phải giống nhau: "Viết chương 2" và "Viết chương 3" là HAI việc khác nhau
      dù chữ giống tới 92%.
    """
    na, nb = norm_no_accent(a), norm_no_accent(b)
    if set(re.findall(r"\d+", na)) != set(re.findall(r"\d+", nb)):
        return False
    return fuzz.token_set_ratio(na, nb) >= DUPLICATE_THRESHOLD


def _assignee_key(it: ExtractedItem) -> tuple[str, int | str]:
    """Khóa nhận diện người làm khi gộp trùng: ưu tiên `assignee_id` nếu đã ghép được tài khoản.

    Trong Online Meeting, câu tự nhận ghi họ tên đầy đủ ("Nguyễn Văn Nam") còn câu chốt cuối
    buổi chỉ ghi tên gọi ("Nam") — cả hai cùng `assignee_id` nên phải được coi là một người.
    """
    if it.assignee_id is not None:
        return ("id", it.assignee_id)
    return ("name", norm_no_accent(strip_honorific(it.raw_assignee or "")))


def _dedupe(items: list[ExtractedItem]) -> list[ExtractedItem]:
    """Gộp đầu việc trùng (cùng người làm, cùng việc). Xảy ra khi cuối họp nhắc lại
    ("chốt lại: Lan viết chương hai...") hoặc khi 2 đoạn gối đầu cùng trích một việc.
    Giữ bản mô tả đầy đủ hơn; bản nào có hạn chót thì lấy hạn chót."""
    kept: list[ExtractedItem] = []
    for it in items:
        who = _assignee_key(it)
        dup = next(
            (k for k in kept if _assignee_key(k) == who and same_task(k.title, it.title)),
            None,
        )
        if dup is None:
            kept.append(it)
            continue
        if len(it.title) > len(dup.title):  # bản sau mô tả đầy đủ hơn → lấy tiêu đề + câu gốc của nó
            dup.title = it.title
            if it.evidence_found or not dup.evidence_found:
                dup.evidence_quote, dup.evidence_found = it.evidence_quote, it.evidence_found
                dup.evidence_segment, dup.evidence_start = it.evidence_segment, it.evidence_start
            if it.due_date is not None:
                dup.due_text, dup.due_date, dup.due_approximate = it.due_text, it.due_date, it.due_approximate
        elif dup.due_date is None and it.due_date is not None:  # bản trùng có hạn chót → lấy hạn chót
            dup.due_text, dup.due_date, dup.due_approximate = it.due_text, it.due_date, it.due_approximate
        if it.assignee_match == "speaker" and dup.assignee_match != "speaker":
            dup.assignee_match, dup.assignee_score = it.assignee_match, it.assignee_score
        if it.priority == "high":
            dup.priority = "high"
    return kept


# ---------- Hàm chính ----------


def _call(llm: LLMProvider, system: str, user: str, schema: dict[str, Any], model: type[BaseModel]) -> BaseModel:
    """Gọi LLM rồi kiểm tra kết quả. JSON sai cấu trúc → thử lại 1 lần trước khi báo lỗi."""
    last: Exception | None = None
    for _ in range(2):
        try:
            return model.model_validate(llm.generate_json(system, user, schema))
        except ValidationError as e:
            last = e
            log.warning("LLM trả về JSON sai cấu trúc, thử lại: %s", str(e)[:200])
    raise LLMError("Mô hình AI trả về dữ liệu sai cấu trúc sau 2 lần thử") from last


def extract_meeting(
    llm: LLMProvider,
    segments: list[dict[str, Any]],
    meeting_date: date,
    members: list[MemberInfo],
    on_progress: Callable[[float], None] | None = None,
    chunk_chars: int | None = None,
    include_members: bool = True,
    on_notice: Callable[[str], None] | None = None,
    use_speakers: bool = True,
) -> ExtractionResult:
    """Tóm tắt + trích xuất đầu việc từ bản ghi.

    `include_members=False` dùng cho thí nghiệm "có / không đưa danh sách thành viên vào prompt".
    `use_speakers=False` dùng cho thí nghiệm "có / không có nhãn người nói" (Online Meeting): bỏ
    tên người nói khỏi các dòng đưa cho LLM, coi như bản ghi từ file ghi âm thường.
    `on_notice(thông báo)`: được gọi khi LLM phải chuyển sang mô hình dự phòng (để hiện lên giao diện).
    """
    t0 = time.perf_counter()
    lines = transcript_lines(segments, with_speakers=use_speakers)
    speakers = speaker_labels(segments) if use_speakers else {}
    if not lines:
        raise LLMError("Bản ghi trống, không có gì để tóm tắt")
    begin_job = getattr(llm, "begin_job", None)
    if begin_job:  # mỗi lần tóm tắt lại thử mô hình chính trước
        begin_job(on_notice)

    prompt_members = [(m.full_name, m.nicknames) for m in members] if include_members else []
    chunks = chunk_lines(lines, chunk_chars or llm.max_input_chars)
    n = len(chunks)
    tokens = {"input_tokens": 0, "output_tokens": 0}

    def add_usage() -> None:
        usage = getattr(llm, "last_usage", None) or {}
        for k in tokens:
            tokens[k] += int(usage.get(k) or 0)

    def report(done: float) -> None:
        if on_progress:
            on_progress(min(1.0, done))

    # Bước "map": mỗi đoạn gọi LLM 1 lần. Có thêm 1 lần gọi "reduce" nếu nhiều hơn 1 đoạn.
    total_calls = n + (1 if n > 1 else 0)
    partial: list[LLMOutput] = []
    for i, chunk in enumerate(chunks, 1):
        user = build_user_prompt(meeting_date, prompt_members, "\n".join(chunk), part=(i, n) if n > 1 else None)
        out = _call(llm, SYSTEM_PROMPT, user, EXTRACTION_SCHEMA, LLMOutput)
        assert isinstance(out, LLMOutput)
        partial.append(out)
        add_usage()
        report(i / total_calls)

    raw_items = [it for p in partial for it in p.action_items]
    if n == 1:
        summary = partial[0].summary
    else:
        # Bước "reduce": gộp các bản tóm tắt từng phần thành một biên bản
        merged = _call(
            llm,
            REDUCE_SYSTEM_PROMPT,
            build_reduce_prompt([p.summary.model_dump() for p in partial]),
            SUMMARY_SCHEMA,
            LLMSummary,
        )
        assert isinstance(merged, LLMSummary)
        summary = merged
        add_usage()
        report(1.0)

    items = _postprocess(raw_items, segments, meeting_date, members, speakers)
    return ExtractionResult(
        summary=summary.model_dump(),
        items=items,
        llm_model=llm.name,
        chunk_count=n,
        processing_sec=round(time.perf_counter() - t0, 2),
        fallback_from=getattr(llm, "fallback_from", None),
        **tokens,
    )
