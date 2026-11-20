"""Chấm điểm bước trích xuất đầu việc (GĐ4 & GĐ7) cho 1 cuộc họp hoặc hàng loạt cả bộ dữ liệu.

Với mỗi cuộc họp có đáp án chuẩn (`expected_tasks.json`), chạy đúng pipeline của MeetFlow
(LLM → ghép tên → tính ngày → kiểm tra câu gốc) rồi đo:
  - Precision / Recall / F1 theo tiêu đề (Micro gộp toàn bộ đầu việc + Macro theo cuộc họp, Macro
    loại cuộc họp không có đầu việc nào trong đáp án), kèm khoảng tin cậy bootstrap 95%.
  - **Strict P/R/F1 (end-to-end)**: một đầu việc chỉ tính ĐÚNG khi khớp tiêu đề + đúng người làm +
    đúng hạn chót — đây là con số "người dùng thực sự nhận được thẻ đúng".
  - Độ đúng người làm (trên các cặp đã khớp; tách lỗi "bỏ trống" và "sai người"), riêng nhóm việc
    tự nhận `self_claimed` (độ đúng + recall trên toàn bộ việc tự nhận của đáp án).
  - Độ đúng hạn chót (tổng, riêng việc có hạn) và tỉ lệ "bịa hạn" (đáp án không có hạn mà AI gán hạn).
  - Bảng độ nhạy theo ngưỡng ghép tiêu đề 50/60/70/80.
  - Danh sách cặp đã ghép (kèm điểm) để kiểm tra tay; bỏ sót (FN), bịa thêm (FP), sai người, sai hạn.

Ghép đầu việc AI ↔ đáp án (`match_tasks`) — luật được cố định TRƯỚC khi chạy thực nghiệm:
  1. `token_set_ratio` (so không dấu) ≥ 60.
  2. Tập con số trong 2 tiêu đề phải bằng nhau ("chương 2" ≠ "chương 3"); số thuộc biểu thức ngày giờ
     ("trước 25/11", "thứ 6", "thứ hai", "9h") bị bỏ qua; số viết bằng chữ cũng được nhận ("chương hai",
     "phần ba", "mười đoạn", "hai mươi lăm"; từ mơ hồ như "một/ba/năm" chỉ tính khi đứng sau danh từ đánh số).
  3. Tiêu đề ngắn (bên ngắn hơn ≤ 2 từ) phải gần như nguyên văn: `fuzz.ratio` ≥ 85 — tránh việc
     "Làm" hay "Gửi email" khớp với mọi đầu việc chứa các từ đó (token_set_ratio cho 100).
  4. Ghép 1–1 TỐI ƯU (thuật toán Hungary): tối đa số cặp trước, rồi tổng điểm tiêu đề, rồi số cặp
     đúng người làm, rồi số cặp đúng hạn (không dùng tham lam vì tham lam có thể bỏ sót cặp).

Chạy LLM với temperature = 0, mỗi cấu hình 1 lần. Lưu đệm (cache) chỉ lưu PHẢN HỒI THÔ của LLM,
khóa theo toàn bộ tham số + nội dung bản ghi, và kiểm tra lại từng prompt khi dùng lại → đổi đáp án,
đổi luật chấm, đổi danh sách thành viên đều được chấm lại ngay mà không gọi lại LLM.

Cách dùng (chạy từ thư mục gốc dự án):
  backend\\.venv\\Scripts\\python experiments\\eval_extraction.py --model gemini-3.5-flash
  backend\\.venv\\Scripts\\python experiments\\eval_extraction.py --data experiments/data --model gemini-3.5-flash --sleep 2
  backend\\.venv\\Scripts\\python experiments\\eval_extraction.py --data experiments/data --use-speakers
  backend\\.venv\\Scripts\\python experiments\\eval_extraction.py --data experiments/data --transcript-dir experiments/results/stt_transcripts/faster-whisper__large-v3-turbo__prompt
  backend\\.venv\\Scripts\\python experiments\\eval_extraction.py --data experiments/data --provider ollama --model qwen2.5:3b
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import date
import hashlib
import inspect
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    DEFAULT_DATA_DIR,
    DEFAULT_RESULTS_DIR,
    MeetingCase,
    bootstrap_ci,
    discover_meetings,
    fmt_ci,
    fmt_pct,
    load_backend_settings,
    parse_transcript_segments,
    resolve_member,
    rnd,
    safe_div,
    select_cases,
    warn_roster,
    write_json,
)

from pydantic import ValidationError  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402

from app.ai import extraction as extraction_module  # noqa: E402
from app.ai.extraction import ExtractedItem, extract_meeting  # noqa: E402
from app.ai.llm import prompts as prompts_module  # noqa: E402
from app.ai.llm.base import LLMError, LLMProvider  # noqa: E402
from app.ai.llm.gemini_provider import GeminiProvider  # noqa: E402
from app.ai.llm.ollama_provider import OllamaProvider  # noqa: E402
from app.ai.postprocess.name_matching import GROUP_WORDS, SELF_WORDS, MemberInfo, strip_honorific  # noqa: E402
from app.ai.postprocess.text_utils import norm, norm_no_accent  # noqa: E402

TITLE_THRESHOLD = 60
SHORT_TITLE_MAX_WORDS = 2
SHORT_TITLE_MIN_RATIO = 85
SENSITIVITY_THRESHOLDS = (50, 60, 70, 80)
EXPERIMENT_TEMPERATURE = 0.0
CACHE_VERSION = 3

# Cấu hình danh sách thành viên (TN2):
#   full        — như production: danh sách thành viên + biệt danh vào prompt VÀ dùng để ghép tên.
#   prompt_only — ablation CHỈ PROMPT: bỏ danh sách khỏi prompt, hậu xử lý vẫn ghép tên/biệt danh.
#   none        — không có thành viên nào (members=[]): không prompt, không ghép tên; người làm được
#                 chấm theo chữ AI viết ra (phải là họ tên hoặc tên gọi thật, biệt danh không tính).
MEMBER_MODES = ("full", "prompt_only", "none")
MEMBER_MODE_LABELS = {
    "full": "",
    "prompt_only": " (bỏ DS thành viên khỏi prompt)",
    "none": " (không có thành viên)",
}


# =============================================================================
# 1. LLM provider
# =============================================================================


def build_llm(provider: str | None = None, model: str | None = None, allow_fallback: bool = False) -> LLMProvider:
    """Khởi tạo LLMProvider cho thực nghiệm: temperature = 0 cho MỌI provider.

    Mặc định tắt `fallback_model` để đo công bằng từng mô hình; `allow_fallback=True` = cấu hình production.
    """
    s = load_backend_settings()
    provider = provider or s.LLM_PROVIDER
    if provider == "gemini":
        fb = s.GEMINI_FALLBACK_MODEL if allow_fallback else ""
        return GeminiProvider(s.GEMINI_API_KEY, model or s.GEMINI_MODEL, EXPERIMENT_TEMPERATURE, s.LLM_TIMEOUT_SEC, fallback_model=fb)
    if provider == "ollama":
        return OllamaProvider(s.OLLAMA_URL, model or s.OLLAMA_MODEL, s.OLLAMA_NUM_CTX, s.OLLAMA_KEEP_ALIVE, EXPERIMENT_TEMPERATURE)
    raise ValueError(f"Không hỗ trợ provider: {provider}")


# =============================================================================
# 2. Ghép đầu việc AI ↔ đáp án
# =============================================================================

# Danh từ đánh số: sau các từ này, cả số "mơ hồ" (một, ba, bốn, tư, năm) cũng được hiểu là con số
_NUMBERED_1 = {
    "chương", "phần", "mục", "bài", "tuần", "buổi", "trang", "slide", "câu", "nhóm", "bước", "sprint",
    "chặng", "vòng", "bản", "module", "tiết", "đợt", "tập", "kỳ", "lab", "task", "số", "version",
}
_NUMBERED_2 = {"giai đoạn", "phiên bản", "học phần"}
_UNITS = {"một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5, "lăm": 5, "sáu": 6, "bảy": 7, "tám": 8, "chín": 9}
_UNAMBIGUOUS = {"hai", "sáu", "bảy", "tám", "chín"}  # "một" (mạo từ), "ba" (bố), "năm" (năm học)... thì mơ hồ
_DATE_BEFORE = {"thứ", "ngày", "tháng", "mùng", "mồng", "lúc", "năm"}  # "thứ hai", "tháng mười một"
_DATE_AFTER = {"tháng", "giờ", "h", "phút", "rưỡi"}  # "hai mươi lăm tháng mười một", "hai giờ"
_DATE_TIME_RE = re.compile(
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"  # 25/11, 25/11/2026
    r"|\b(?:thứ|ngày|tháng|năm|mùng|mồng|lúc)\s+\d+\b"  # thứ 6, ngày 25, tháng 11
    r"|\b\d{1,2}\s*(?:h|giờ|g)(?:\s*\d{1,2})?\b"  # 9h, 9 giờ 30
    r"|\b\d{1,2}:\d{2}\b"
)


def _spelled_numbers(tokens: list[str]) -> set[int]:
    """Số viết bằng chữ: "mười", "hai mươi lăm", "chương hai", "phần ba" (bỏ ngày giờ như "thứ hai")."""
    nums: set[int] = set()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        prev = tokens[i - 1] if i > 0 else ""
        prev2 = " ".join(tokens[i - 2 : i]) if i > 1 else ""
        val: int | None = None
        j = i + 1
        if tok == "mười":
            val = 10
            if j < len(tokens) and tokens[j] in _UNITS and tokens[j] != "mốt":
                val, j = 10 + _UNITS[tokens[j]], j + 1
        elif tok in _UNITS and tok not in ("lăm", "mốt") and j < len(tokens) and tokens[j] == "mươi":
            val, j = 10 * _UNITS[tok], j + 1
            if j < len(tokens) and tokens[j] in _UNITS:
                val, j = val + _UNITS[tokens[j]], j + 1
        elif tok in _UNITS and tok not in ("lăm", "mốt") and (tok in _UNAMBIGUOUS or prev in _NUMBERED_1 or prev2 in _NUMBERED_2):
            val = _UNITS[tok]
        if val is None:
            i += 1
            continue
        nxt = tokens[j] if j < len(tokens) else ""
        if prev not in _DATE_BEFORE and nxt not in _DATE_AFTER:
            nums.add(val)
        i = j
    return nums


def title_numbers(title: str) -> set[int]:
    """Các con số "định danh" trong tiêu đề (chương 2, 10 đoạn ghi âm), bỏ số thuộc ngày giờ.

    Nhận cả chữ số lẫn số viết bằng chữ ("chương hai" = "chương 2", "mười đoạn" = "10 đoạn").
    """
    t = unicodedata.normalize("NFC", title.lower())
    t = _DATE_TIME_RE.sub(" ", t)
    nums = {int(x) for x in re.findall(r"\d+", t)}
    return nums | _spelled_numbers(re.findall(r"[^\W\d_]+", t))


def title_score(expected_title: str, predicted_title: str, threshold: int = TITLE_THRESHOLD) -> int | None:
    """Điểm giống nhau của 2 tiêu đề nếu đủ điều kiện ghép, ngược lại None (xem luật ở đầu file)."""
    ne, np_ = norm_no_accent(str(expected_title)), norm_no_accent(str(predicted_title))
    if not ne or not np_:
        return None
    score = int(fuzz.token_set_ratio(ne, np_))
    if score < threshold:
        return None
    if title_numbers(str(expected_title)) != title_numbers(str(predicted_title)):
        return None
    if min(len(ne.split()), len(np_.split())) <= SHORT_TITLE_MAX_WORDS and fuzz.ratio(ne, np_) < SHORT_TITLE_MIN_RATIO:
        return None
    return score


def _is_blank_assignee(predicted: ExtractedItem) -> bool:
    """Hệ thống KHÔNG chỉ định ai (để trống, đại từ "em/anh", hoặc "cả nhóm")."""
    if predicted.assignee_id is not None:
        return False
    raw = norm(predicted.raw_assignee or "")
    return not raw or raw in SELF_WORDS or raw in GROUP_WORDS


def _name_forms(m: MemberInfo) -> set[str]:
    """Cách gọi THẬT của một thành viên (họ tên, tên gọi = chữ cuối) — không gồm biệt danh."""
    full = norm_no_accent(m.full_name)
    parts = full.split()
    return {full, parts[-1]} if parts else {full}


def assignee_matches(
    expected_assignee: str | None,
    predicted: ExtractedItem,
    members: list[MemberInfo],
    linking: str = "system",
) -> bool:
    """Đầu việc AI có đúng người làm so với đáp án không.

    - `linking="system"` (mặc định): hệ thống phải ghép đúng TÀI KHOẢN (`assignee_id`).
    - `linking="name_text"` (cấu hình không có thành viên): hệ thống không có tài khoản nào để ghép,
      nên chấm theo chữ AI viết: phải là họ tên hoặc tên gọi thật của người đó (biệt danh không tính).
    - Đáp án không có người làm → đúng khi hệ thống cũng để trống (không phải tên người ngoài).
    - Người ngoài nhóm (F20, không có trong `members`) → so theo tên chữ đã bỏ xưng hô, không dấu.
    """
    if not expected_assignee or not str(expected_assignee).strip():
        return _is_blank_assignee(predicted)
    member = resolve_member(str(expected_assignee), members)
    if member is not None:
        if predicted.assignee_id is not None:
            return predicted.assignee_id == member.user_id
        if linking == "name_text":
            return norm_no_accent(strip_honorific(predicted.raw_assignee or "")) in _name_forms(member)
        return False
    if predicted.assignee_id is not None:
        return False
    return norm_no_accent(strip_honorific(predicted.raw_assignee or "")) == norm_no_accent(strip_honorific(str(expected_assignee)))


def due_matches(expected_due: str | None, predicted: ExtractedItem) -> bool:
    pred_due = predicted.due_date.isoformat() if predicted.due_date else None
    exp_due = str(expected_due).strip() if expected_due else None
    return pred_due == exp_due


def _hungarian_max(weights: list[list[int]]) -> list[tuple[int, int]]:
    """Ghép 1–1 có tổng trọng số LỚN NHẤT (Kuhn–Munkres, O(n²m)). `weights[i][j] = 0` = không được ghép.

    Thuần Python, số nguyên chính xác tùy ý (không cần scipy). Trả về các cặp (i, j) có trọng số > 0.
    """
    n = len(weights)
    m = len(weights[0]) if n else 0
    if n == 0 or m == 0:
        return []
    transpose = n > m
    w = [list(col) for col in zip(*weights, strict=True)] if transpose else weights
    rows, cols = len(w), len(w[0])
    cost = [[-w[i][j] for j in range(cols)] for i in range(rows)]
    inf = float("inf")
    u = [0] * (rows + 1)
    v = [0] * (cols + 1)
    p = [0] * (cols + 1)
    way = [0] * (cols + 1)
    for i in range(1, rows + 1):
        p[0] = i
        j0 = 0
        minv: list[Any] = [inf] * (cols + 1)
        used = [False] * (cols + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, cols + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(cols + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    pairs: list[tuple[int, int]] = []
    for j in range(1, cols + 1):
        i = p[j]
        if i and w[i - 1][j - 1] > 0:
            pairs.append((j - 1, i - 1) if transpose else (i - 1, j - 1))
    return sorted(pairs)


def match_tasks(
    expected: list[dict[str, Any]],
    predicted: list[ExtractedItem],
    members: list[MemberInfo] | None = None,
    threshold: int = TITLE_THRESHOLD,
    linking: str = "system",
) -> list[tuple[dict[str, Any], ExtractedItem, int]]:
    """Ghép 1–1 TỐI ƯU: tối đa số cặp → tổng điểm tiêu đề → số cặp đúng người → số cặp đúng hạn.

    Mã hóa thứ tự ưu tiên thành MỘT trọng số nguyên (mỗi tầng lớn hơn tổng mọi tầng dưới), rồi giải
    bài toán ghép cặp trọng số lớn nhất bằng thuật toán Hungary. Mỗi đáp án/dự đoán dùng tối đa 1 lần.
    """
    members = members or []
    if not expected or not predicted:
        return []
    base = max(len(expected), len(predicted)) + 1
    weights = [[0] * len(predicted) for _ in expected]
    scores: dict[tuple[int, int], int] = {}
    for ei, e in enumerate(expected):
        for pi, p in enumerate(predicted):
            score = title_score(str(e.get("task", "")), p.title, threshold)
            if score is None:
                continue
            who_ok = int(assignee_matches(e.get("assignee"), p, members, linking))
            due_ok = int(due_matches(e.get("due_date"), p))
            weights[ei][pi] = (((101 * base) + score) * base + who_ok) * base + due_ok
            scores[(ei, pi)] = score
    return [(expected[ei], predicted[pi], scores[(ei, pi)]) for ei, pi in _hungarian_max(weights)]


# =============================================================================
# 3. Chạy LLM (có lưu đệm phản hồi thô) và chấm điểm
# =============================================================================


def resolve_transcript_source(
    case: MeetingCase,
    transcript: Path | None = None,
    transcript_dir: Path | None = None,
    prefer_speakers: bool = False,
    source: str | None = None,
) -> Path:
    """Chọn file bản ghi đầu vào cho 1 cuộc họp.

    Thứ tự: file chỉ định → thư mục STT → `source` chỉ định rõ (`reference` | `reference_speakers` |
    `online_segments`) → bản chuẩn (`reference_speakers.txt` nếu `prefer_speakers`, không thì `reference.txt`).
    """
    if transcript is not None:
        return transcript
    if transcript_dir is not None:
        for ext in (".json", ".txt"):
            p = transcript_dir / f"{case.meeting_id}{ext}"
            if p.exists():
                return p
        raise FileNotFoundError(f"Không tìm thấy bản ghi của `{case.meeting_id}` trong {transcript_dir}")
    if source == "online_segments":
        if not case.has_online_segments:
            raise FileNotFoundError(f"`{case.meeting_id}` không có online_segments.json có speaker_id")
        assert case.online_segments_path is not None
        return case.online_segments_path
    if source == "reference_speakers":
        if not case.has_speaker_reference:
            raise FileNotFoundError(f"`{case.meeting_id}` không có reference_speakers.txt")
        assert case.reference_speakers_path is not None
        return case.reference_speakers_path
    if source == "reference":
        if not case.has_reference:
            raise FileNotFoundError(f"`{case.meeting_id}` không có reference.txt")
        assert case.reference_path is not None
        return case.reference_path
    if prefer_speakers and case.has_speaker_reference:
        assert case.reference_speakers_path is not None
        return case.reference_speakers_path
    if case.has_reference:
        assert case.reference_path is not None
        return case.reference_path
    if case.has_speaker_reference:
        assert case.reference_speakers_path is not None
        return case.reference_speakers_path
    raise FileNotFoundError(f"Cuộc họp `{case.meeting_id}` không có reference.txt hay reference_speakers.txt")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _prompt_sha(system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> str:
    payload = json.dumps([system_prompt, user_prompt, schema], ensure_ascii=False, sort_keys=True)
    return _sha256(payload.encode("utf-8"))


_CODE_VERSION: str | None = None


def pipeline_code_version() -> str:
    """Băm mã nguồn prompt + trích xuất của backend — ghi vào kết quả để biết số liệu sinh từ bản code nào."""
    global _CODE_VERSION
    if _CODE_VERSION is None:
        src = inspect.getsource(prompts_module) + inspect.getsource(extraction_module)
        _CODE_VERSION = _sha256(src.encode("utf-8"))[:12]
    return _CODE_VERSION


class CacheMismatch(Exception):
    """Prompt hiện tại khác prompt đã lưu → phải gọi LLM thật."""


class _RecordingLLM:
    """Bọc LLM thật, ghi lại từng (băm prompt, phản hồi thô, token) để lưu đệm."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.name = inner.name
        self.max_input_chars = inner.max_input_chars
        self.calls: list[dict[str, Any]] = []
        self.last_usage: dict[str, Any] | None = None

    def generate_json(self, system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        out = self._inner.generate_json(system_prompt, user_prompt, schema)
        self.last_usage = dict(getattr(self._inner, "last_usage", None) or {})
        self.calls.append({"prompt_sha": _prompt_sha(system_prompt, user_prompt, schema), "response": out, "usage": self.last_usage})
        return out

    def __getattr__(self, item: str) -> Any:  # begin_job, fallback_from... của provider thật
        return getattr(self._inner, item)


class _ReplayLLM:
    """Phát lại phản hồi đã lưu; prompt nào khác bản đã lưu → `CacheMismatch`."""

    def __init__(self, cached: dict[str, Any]) -> None:
        self.name = cached["llm_name"]
        self.max_input_chars = int(cached["max_input_chars"])
        self.fallback_from = cached.get("fallback_from")
        self._calls = list(cached["calls"])
        self.last_usage: dict[str, Any] | None = None

    def generate_json(self, system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        if not self._calls:
            raise CacheMismatch("số lần gọi LLM khác bản đã lưu")
        call = self._calls.pop(0)
        if call["prompt_sha"] != _prompt_sha(system_prompt, user_prompt, schema):
            raise CacheMismatch("prompt khác bản đã lưu")
        self.last_usage = call.get("usage") or {}
        return call["response"]


def is_model_output_error(e: BaseException) -> bool:
    """Lỗi do MÔ HÌNH trả kết quả hỏng (JSON sai/rỗng/sai cấu trúc) — khác lỗi mạng/hạn mức."""
    cur: BaseException | None = e
    for _ in range(6):
        if cur is None:
            break
        if isinstance(cur, (ValidationError, json.JSONDecodeError)):
            return True
        cur = cur.__cause__ or cur.__context__
    msg = str(e)
    return any(k in msg for k in ("JSON", "sai cấu trúc", "sai định dạng", "kết quả rỗng"))


def _members_for_mode(case: MeetingCase, member_mode: str) -> tuple[list[MemberInfo], bool]:
    """(members truyền vào extract_meeting, include_members) theo cấu hình danh sách thành viên."""
    if member_mode not in MEMBER_MODES:
        raise ValueError(f"member_mode không hợp lệ: {member_mode!r}")
    if member_mode == "none":
        return [], False
    return case.members, member_mode == "full"


def run_extraction(
    llm_factory: Callable[[], Any] | Any,
    case: MeetingCase,
    *,
    transcript_path: Path,
    member_mode: str = "full",
    use_speakers: bool = False,
    chunk_chars: int | None = None,
    cache_file: Path | None = None,
    use_cache: bool = False,
) -> dict[str, Any]:
    """Chạy `extract_meeting` (hoặc phát lại từ cache) → kết quả THÔ chưa chấm điểm.

    `llm_factory` có thể là 1 LLM hoặc hàm tạo LLM (chỉ gọi khi thật sự cần gọi API).
    Lỗi do mô hình trả kết quả hỏng → hàng "thất bại" (mọi đầu việc đáp án tính là FN) chứ không dừng
    cả thí nghiệm. Lỗi mạng / hạn mức → ném ra để dừng (chạy lại với --skip-existing sẽ tiếp tục).
    """
    assert case.meeting_date is not None, f"Cuộc họp {case.meeting_id} thiếu meeting_date"
    speaker_format = transcript_path.name.endswith("_speakers.txt")
    parse_sp = use_speakers or speaker_format or transcript_path.suffix.lower() == ".json"
    segments = parse_transcript_segments(transcript_path, case.members, parse_speakers=parse_sp, speaker_format=speaker_format)
    members, include_members = _members_for_mode(case, member_mode)
    base = {
        "meeting_id": case.meeting_id,
        "transcript_source": str(transcript_path),
        "transcript_sha256": _sha256(transcript_path.read_bytes())[:16],
        "member_mode": member_mode,
        "include_members": include_members,
        "use_speakers": use_speakers,
        "segments_count": len(segments),
        "code_version": pipeline_code_version(),
    }

    def finish(result: Any, from_cache: bool, processing_sec: float | None = None) -> dict[str, Any]:
        return {
            **base,
            "failed": False,
            "error": None,
            "from_cache": from_cache,
            "model": result.llm_model,
            "fallback_from": result.fallback_from,
            "processing_sec": processing_sec if processing_sec is not None else result.processing_sec,
            "chunk_count": result.chunk_count,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "summary": result.summary,
            "items": [p.to_dict() for p in result.items],
        }

    def call(llm: Any) -> Any:
        return extract_meeting(
            llm,
            segments,
            case.meeting_date,
            members,
            chunk_chars=chunk_chars,
            include_members=include_members,
            use_speakers=use_speakers,
        )

    if use_cache and cache_file is not None and cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("cache_version") == CACHE_VERSION:
            try:
                res = call(_ReplayLLM(cached))
                return finish(res, True, cached.get("processing_sec"))
            except CacheMismatch:
                pass

    llm = llm_factory() if callable(llm_factory) and not hasattr(llm_factory, "generate_json") else llm_factory
    rec = _RecordingLLM(llm)
    try:
        res = call(rec)
    except LLMError as e:
        if not is_model_output_error(e):
            raise
        return {
            **base,
            "failed": True,
            "error": str(e)[:300],
            "from_cache": False,
            "model": getattr(llm, "name", "?"),
            "fallback_from": None,
            "processing_sec": 0.0,
            "chunk_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "summary": None,
            "items": [],
        }
    if cache_file is not None:
        write_json(
            cache_file,
            {
                "cache_version": CACHE_VERSION,
                "meeting_id": case.meeting_id,
                "llm_name": rec.name,
                "max_input_chars": rec.max_input_chars,
                "fallback_from": res.fallback_from,
                "processing_sec": res.processing_sec,
                "calls": rec.calls,
            },
        )
    return finish(res, False)


def _item_from_dict(d: dict[str, Any]) -> ExtractedItem:
    data = dict(d)
    data["due_date"] = date.fromisoformat(data["due_date"]) if data.get("due_date") else None
    return ExtractedItem(**data)


def _prf(tp: int, n_pred: int, n_exp: int) -> tuple[float | None, float | None, float | None]:
    """P = tp/dự đoán, R = tp/đáp án, F1 = 2tp/(2tp+fp+fn). Mẫu số 0 → None (không định nghĩa)."""
    p = safe_div(tp, n_pred)
    r = safe_div(tp, n_exp)
    f1 = safe_div(2 * tp, n_pred + n_exp)
    return p, r, f1


def score_case(case: MeetingCase, raw: dict[str, Any], threshold: int = TITLE_THRESHOLD) -> dict[str, Any]:
    """Chấm kết quả thô của 1 cuộc họp với đáp án HIỆN TẠI (luôn chấm lại, không lấy điểm từ cache)."""
    expected = case.expected_tasks
    predicted = [_item_from_dict(d) for d in raw["items"]]
    members = case.members
    linking = "name_text" if raw.get("member_mode") == "none" else "system"
    pairs = match_tasks(expected, predicted, members, threshold, linking)
    name_of = {m.user_id: m.full_name for m in members}

    tp, n_pred, n_exp = len(pairs), len(predicted), len(expected)
    precision, recall, f1 = _prf(tp, n_pred, n_exp)

    who_ok = due_ok = strict_tp = 0
    who_blank = who_wrong = 0
    due_with_date_total = due_with_date_ok = 0
    gold_no_due = spurious_due = 0
    self_exp_total = sum(1 for e in expected if e.get("self_claimed"))
    self_matched = self_ok = self_blank = self_wrong = 0
    self_left_blank = speaker_match_count = 0
    assignee_errors: list[dict[str, Any]] = []
    due_errors: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []

    exp_index = {id(e): i for i, e in enumerate(expected)}
    pred_index = {id(p): i for i, p in enumerate(predicted)}
    for e, p, title_sc in pairs:
        w_ok = assignee_matches(e.get("assignee"), p, members, linking)
        d_ok = due_matches(e.get("due_date"), p)
        blank = _is_blank_assignee(p)
        matches.append(
            {
                "gold_index": exp_index[id(e)],
                "gold_task": e.get("task"),
                "pred_index": pred_index[id(p)],
                "pred_title": p.title,
                "title_score": title_sc,
                "assignee_ok": w_ok,
                "due_ok": d_ok,
            }
        )
        if w_ok:
            who_ok += 1
        else:
            who_blank += int(blank)
            who_wrong += int(not blank)
            assignee_errors.append(
                {
                    "task": e.get("task"),
                    "predicted_task": p.title,
                    "expected_assignee": e.get("assignee"),
                    "predicted_assignee": name_of.get(p.assignee_id) or p.raw_assignee,
                    "assignee_match": p.assignee_match,
                    "error_type": "blank" if blank else "wrong_person",
                    "self_claimed": bool(e.get("self_claimed")),
                }
            )
        if d_ok:
            due_ok += 1
        else:
            due_errors.append(
                {
                    "task": e.get("task"),
                    "expected_due": e.get("due_date"),
                    "predicted_due": p.due_date.isoformat() if p.due_date else None,
                    "due_text": p.due_text,
                }
            )
        if w_ok and d_ok:
            strict_tp += 1
        if e.get("due_date"):
            due_with_date_total += 1
            due_with_date_ok += int(d_ok)
        else:
            gold_no_due += 1
            spurious_due += int(p.due_date is not None)
        if e.get("self_claimed"):
            self_matched += 1
            if w_ok:
                self_ok += 1
            elif blank:
                self_blank += 1
            else:
                self_wrong += 1
        if p.assignee_match == "self":
            self_left_blank += 1
        if p.assignee_match == "speaker":
            speaker_match_count += 1

    s_p, s_r, s_f1 = _prf(strict_tp, n_pred, n_exp)
    sensitivity = {str(th): len(match_tasks(expected, predicted, members, th, linking)) for th in SENSITIVITY_THRESHOLDS}
    matched_e = {m["gold_index"] for m in matches}
    matched_p = {m["pred_index"] for m in matches}
    evidence_ok = sum(1 for p in predicted if p.evidence_found)

    return {
        **{k: raw[k] for k in raw if k not in ("items", "summary")},
        "expected_count": n_exp,
        "predicted_count": n_pred,
        "title_threshold": threshold,
        "tp": tp,
        "fp": n_pred - tp,
        "fn": n_exp - tp,
        "precision": rnd(precision),
        "recall": rnd(recall),
        "f1": rnd(f1),
        "strict_tp": strict_tp,
        "strict_precision": rnd(s_p),
        "strict_recall": rnd(s_r),
        "strict_f1": rnd(s_f1),
        "assignee_correct": who_ok,
        "assignee_blank": who_blank,
        "assignee_wrong": who_wrong,
        "assignee_acc": rnd(safe_div(who_ok, tp)),
        "self_claimed_expected": self_exp_total,
        "self_claimed_matched": self_matched,
        "self_claimed_correct": self_ok,
        "self_claimed_blank": self_blank,
        "self_claimed_wrong": self_wrong,
        "self_claimed_acc": rnd(safe_div(self_ok, self_matched)),
        "self_claimed_recall": rnd(safe_div(self_ok, self_exp_total)),
        "self_left_blank": self_left_blank,
        "speaker_matched": speaker_match_count,
        "due_correct": due_ok,
        "due_acc": rnd(safe_div(due_ok, tp)),
        "due_with_date_total": due_with_date_total,
        "due_with_date_correct": due_with_date_ok,
        "due_with_date_acc": rnd(safe_div(due_with_date_ok, due_with_date_total)),
        "gold_no_due_matched": gold_no_due,
        "spurious_due": spurious_due,
        "spurious_due_rate": rnd(safe_div(spurious_due, gold_no_due)),
        "evidence_found": evidence_ok,
        "evidence_rate": rnd(safe_div(evidence_ok, n_pred)),
        "sensitivity_tp": sensitivity,
        "matches": matches,
        "missed_tasks": [e for i, e in enumerate(expected) if i not in matched_e],
        "extra_tasks": [p.to_dict() for i, p in enumerate(predicted) if i not in matched_p],
        "assignee_errors": assignee_errors,
        "due_errors": due_errors,
        "summary": raw.get("summary"),
        "items": raw["items"],
    }


def evaluate_case(
    llm: Any,
    case: MeetingCase,
    *,
    transcript: Path | None = None,
    transcript_dir: Path | None = None,
    include_members: bool = True,
    member_mode: str | None = None,
    use_speakers: bool = False,
    prefer_speakers: bool = False,
    transcript_source: str | None = None,
    chunk_chars: int | None = None,
    cache_file: Path | None = None,
    use_cache: bool = False,
) -> dict[str, Any]:
    """Chạy + chấm 1 cuộc họp. `member_mode` (full | prompt_only | none) ưu tiên hơn `include_members`."""
    mode = member_mode or ("full" if include_members else "prompt_only")
    src = resolve_transcript_source(case, transcript, transcript_dir, prefer_speakers=prefer_speakers or use_speakers, source=transcript_source)
    raw = run_extraction(
        llm,
        case,
        transcript_path=src,
        member_mode=mode,
        use_speakers=use_speakers,
        chunk_chars=chunk_chars,
        cache_file=cache_file,
        use_cache=use_cache,
    )
    row = score_case(case, raw)
    if transcript_source:
        row["transcript_kind"] = transcript_source
    return row


def cache_file_for(
    cache_dir: Path,
    case: MeetingCase,
    transcript_path: Path,
    params: dict[str, Any],
) -> Path:
    """Đường dẫn file cache: khóa = băm(toàn bộ tham số + nội dung bản ghi + run_id)."""
    key = {
        "cache_version": CACHE_VERSION,
        "temperature": EXPERIMENT_TEMPERATURE,
        "transcript_sha256": _sha256(transcript_path.read_bytes()),
        "transcript_name": transcript_path.name,
        **params,
    }
    digest = _sha256(json.dumps(key, ensure_ascii=False, sort_keys=True).encode("utf-8"))[:20]
    return cache_dir / case.meeting_id / f"{digest}.json"


def evaluate_cases_cached(
    *,
    cases: list[MeetingCase],
    llm_factory: Callable[[], Any],
    provider: str,
    model: str,
    member_mode: str = "full",
    use_speakers: bool = False,
    transcript_dir: Path | None = None,
    transcript_source: str | None = None,
    cache_dir: Path = DEFAULT_RESULTS_DIR / "cache",
    skip_existing: bool = False,
    run_id: str = "r1",
    allow_fallback: bool = False,
    chunk_chars: int | None = None,
    sleep_sec: float = 0.0,
    on_row: Callable[[MeetingCase, dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Chạy 1 cấu hình trên nhiều cuộc họp, dùng lại phản hồi thô đã lưu khi `skip_existing`.

    LLM thật chỉ được tạo khi có ít nhất 1 cuộc họp cần gọi API (xuất lại báo cáo từ cache không cần khóa API).
    """
    holder: dict[str, Any] = {}

    def lazy_llm() -> Any:
        if "llm" not in holder:
            holder["llm"] = llm_factory()
        return holder["llm"]

    rows: list[dict[str, Any]] = []
    live_calls = 0
    for c in cases:
        src = resolve_transcript_source(case=c, transcript_dir=transcript_dir, prefer_speakers=use_speakers, source=transcript_source)
        params = {
            "provider": provider,
            "model": model,
            "allow_fallback": allow_fallback,
            "member_mode": member_mode,
            "use_speakers": use_speakers,
            "chunk_chars": chunk_chars,
            "run_id": run_id,
        }
        cfile = cache_file_for(cache_dir, c, src, params)
        if not (skip_existing and cfile.exists()) and live_calls > 0 and sleep_sec > 0:
            time.sleep(sleep_sec)
        raw = run_extraction(
            lazy_llm,
            c,
            transcript_path=src,
            member_mode=member_mode,
            use_speakers=use_speakers,
            chunk_chars=chunk_chars,
            cache_file=cfile,
            use_cache=skip_existing,
        )
        if not raw["from_cache"]:
            live_calls += 1
        row = score_case(c, raw)
        row["run_id"] = run_id
        if transcript_source:
            row["transcript_kind"] = transcript_source
        rows.append(row)
        if on_row:
            on_row(c, row)
    return rows


# =============================================================================
# 4. Tổng hợp nhiều cuộc họp
# =============================================================================


def _micro(rows: Sequence[dict[str, Any]], tp_key: str = "tp") -> tuple[float | None, float | None, float | None]:
    tp = sum(r[tp_key] for r in rows)
    return _prf(tp, sum(r["predicted_count"] for r in rows), sum(r["expected_count"] for r in rows))


def _mean(vals: list[float | None]) -> float | None:
    xs = [v for v in vals if v is not None]
    return (sum(xs) / len(xs)) if xs else None


def stat_micro_f1(rows: Sequence[dict[str, Any]]) -> float | None:
    return _micro(rows)[2]


def stat_strict_f1(rows: Sequence[dict[str, Any]]) -> float | None:
    return _micro(rows, "strict_tp")[2]


def stat_assignee_acc(rows: Sequence[dict[str, Any]]) -> float | None:
    return safe_div(sum(r["assignee_correct"] for r in rows), sum(r["tp"] for r in rows))


def stat_due_acc(rows: Sequence[dict[str, Any]]) -> float | None:
    return safe_div(sum(r["due_correct"] for r in rows), sum(r["tp"] for r in rows))


def stat_self_claimed_recall(rows: Sequence[dict[str, Any]]) -> float | None:
    return safe_div(sum(r["self_claimed_correct"] for r in rows), sum(r["self_claimed_expected"] for r in rows))


def aggregate_extraction_runs(
    label: str,
    rows: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Tổng hợp Micro / Macro / Strict P-R-F1 + khoảng tin cậy bootstrap 95% (lấy mẫu lại theo cuộc họp).

    Quy ước: tỉ lệ không định nghĩa được (mẫu số 0) → None. Macro chỉ tính trên các cuộc họp có ≥ 1
    đầu việc trong đáp án (cuộc họp không có đầu việc nào không có recall).
    """
    n = len(rows)
    tp = sum(r["tp"] for r in rows)
    exp_total = sum(r["expected_count"] for r in rows)
    pred_total = sum(r["predicted_count"] for r in rows)
    micro_p, micro_r, micro_f1 = _micro(rows)
    s_p, s_r, s_f1 = _micro(rows, "strict_tp")
    macro_rows = [r for r in rows if r["expected_count"] > 0]

    def ci(fn: Callable[[Sequence[dict[str, Any]]], float | None]) -> list[float] | None:
        return bootstrap_ci(rows, fn, seed=seed)

    def s(key: str) -> int:
        return sum(int(r.get(key) or 0) for r in rows)

    sens: dict[str, dict[str, float | None]] = {}
    for th in SENSITIVITY_THRESHOLDS:
        tp_th = sum(int(r["sensitivity_tp"][str(th)]) for r in rows) if rows else 0
        p_, r_, f_ = _prf(tp_th, pred_total, exp_total)
        sens[str(th)] = {"tp": tp_th, "precision": rnd(p_), "recall": rnd(r_), "f1": rnd(f_)}

    chunks = [int(r.get("chunk_count") or 0) for r in rows if not r.get("failed")]
    total_sec = sum(float(r.get("processing_sec") or 0.0) for r in rows)
    failed = [r["meeting_id"] for r in rows if r.get("failed")]

    return {
        "label": label,
        **(meta or {}),
        "temperature": EXPERIMENT_TEMPERATURE,
        "title_threshold": TITLE_THRESHOLD,
        "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": seed, "unit": "meeting"},
        "meetings_count": n,
        "failed_meetings": failed,
        "macro_meetings_count": len(macro_rows),
        "expected_total": exp_total,
        "predicted_total": pred_total,
        "tp": tp,
        "fp": pred_total - tp,
        "fn": exp_total - tp,
        "micro_precision": rnd(micro_p),
        "micro_recall": rnd(micro_r),
        "micro_f1": rnd(micro_f1),
        "micro_precision_ci95": ci(lambda rs: _micro(rs)[0]),
        "micro_recall_ci95": ci(lambda rs: _micro(rs)[1]),
        "micro_f1_ci95": ci(stat_micro_f1),
        "macro_precision": rnd(_mean([r["precision"] for r in macro_rows])),
        "macro_recall": rnd(_mean([r["recall"] for r in macro_rows])),
        "macro_f1": rnd(_mean([r["f1"] for r in macro_rows])),
        "strict_tp": s("strict_tp"),
        "strict_precision": rnd(s_p),
        "strict_recall": rnd(s_r),
        "strict_f1": rnd(s_f1),
        "strict_precision_ci95": ci(lambda rs: _micro(rs, "strict_tp")[0]),
        "strict_recall_ci95": ci(lambda rs: _micro(rs, "strict_tp")[1]),
        "strict_f1_ci95": ci(stat_strict_f1),
        "assignee_correct": s("assignee_correct"),
        "assignee_blank": s("assignee_blank"),
        "assignee_wrong": s("assignee_wrong"),
        "assignee_acc": rnd(stat_assignee_acc(rows)),
        "self_claimed_expected": s("self_claimed_expected"),
        "self_claimed_matched": s("self_claimed_matched"),
        "self_claimed_correct": s("self_claimed_correct"),
        "self_claimed_blank": s("self_claimed_blank"),
        "self_claimed_wrong": s("self_claimed_wrong"),
        "self_claimed_acc": rnd(safe_div(s("self_claimed_correct"), s("self_claimed_matched"))),
        "self_claimed_recall": rnd(stat_self_claimed_recall(rows)),
        "self_left_blank": s("self_left_blank"),
        "speaker_matched": s("speaker_matched"),
        "due_correct": s("due_correct"),
        "due_acc": rnd(stat_due_acc(rows)),
        "due_with_date_total": s("due_with_date_total"),
        "due_with_date_correct": s("due_with_date_correct"),
        "due_with_date_acc": rnd(safe_div(s("due_with_date_correct"), s("due_with_date_total"))),
        "gold_no_due_matched": s("gold_no_due_matched"),
        "spurious_due": s("spurious_due"),
        "spurious_due_rate": rnd(safe_div(s("spurious_due"), s("gold_no_due_matched"))),
        "evidence_found": s("evidence_found"),
        "evidence_rate": rnd(safe_div(s("evidence_found"), pred_total)),
        "threshold_sensitivity": sens,
        "chunk_count_avg": rnd(_mean([float(x) for x in chunks]), 2),
        "chunk_count_max": max(chunks) if chunks else None,
        "total_processing_sec": round(total_sec, 2),
        "avg_processing_sec": round(total_sec / n, 2) if n else None,
        "input_tokens": s("input_tokens"),
        "output_tokens": s("output_tokens"),
        "per_meeting": rows,
    }


def _print_single_report(row: dict[str, Any], members: list[MemberInfo]) -> None:
    name_of = {m.user_id: m.full_name for m in members}
    status = f" | THẤT BẠI: {row['error']}" if row.get("failed") else ""
    print(f"\n[{row['meeting_id']}] Mô hình: {row['model']} | {row['segments_count']} câu | nguồn: {Path(row['transcript_source']).name}{status}")
    print("  Đầu việc AI trích được:")
    for p in row["items"]:
        who = name_of.get(p["assignee_id"]) or f"(chưa ghép: {p['raw_assignee'] or '—'} / {p['assignee_match']})"
        ev = "có" if p["evidence_found"] else "KHÔNG THẤY"
        print(f"    - {p['title']} | {who} | {p['due_date'] or '—'} ({p['due_text'] or 'không nói hạn'}) | câu gốc: {ev}")
    for e in row["missed_tasks"]:
        print(f"    ! BỎ SÓT: {e['task']} ({e.get('assignee') or '—'})")
    print(
        f"  Kết quả: Đáp án {row['expected_count']} | AI {row['predicted_count']} | Khớp {row['tp']} "
        f"| P={fmt_pct(row['precision'])} R={fmt_pct(row['recall'])} F1={fmt_pct(row['f1'])} | Strict F1={fmt_pct(row['strict_f1'])}"
    )
    print(
        f"  Đúng người làm: {row['assignee_correct']}/{row['tp']} (bỏ trống {row['assignee_blank']}, sai người {row['assignee_wrong']}) | "
        f"Đúng hạn: {row['due_correct']}/{row['tp']} | Bịa hạn: {row['spurious_due']}/{row['gold_no_due_matched']} | "
        f"Câu gốc: {row['evidence_found']}/{row['predicted_count']} | "
        f"{row['processing_sec']:.1f}s, {row['chunk_count']} đoạn ({row['input_tokens']} in / {row['output_tokens']} out)"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Chấm điểm trích xuất đầu việc (1 cuộc họp hoặc hàng loạt)")
    ap.add_argument("--data", default=str(DEFAULT_DATA_DIR / "sample_meeting_01"), help="Thư mục 1 cuộc họp HOẶC thư mục cha chứa nhiều cuộc họp")
    ap.add_argument("--transcript", help="File bản ghi khác (chỉ dùng khi chấm 1 cuộc họp)")
    ap.add_argument("--transcript-dir", help="Thư mục chứa bản ghi STT (<meeting_id>.txt/.json) khi chấm hàng loạt")
    ap.add_argument("--provider", choices=["gemini", "ollama"])
    ap.add_argument("--model")
    ap.add_argument("--member-mode", choices=MEMBER_MODES, default="full", help="full | prompt_only (bỏ DS khỏi prompt) | none (members=[])")
    ap.add_argument("--no-members", action="store_true", help="(cũ) = --member-mode prompt_only")
    sp_grp = ap.add_mutually_exclusive_group()
    sp_grp.add_argument("--use-speakers", action="store_true", help="Đọc bản ghi có nhãn người nói và bật use_speakers=True")
    sp_grp.add_argument("--no-speakers", action="store_true", help="Đọc bản ghi có nhãn người nói nhưng tắt use_speakers=False")
    ap.add_argument("--allow-fallback", action="store_true", help="Cho phép Gemini tự chuyển sang mô hình dự phòng")
    ap.add_argument("--include-synthetic", action="store_true", help="Chấm cả cuộc họp giả lập (synthetic: true)")
    ap.add_argument("--sleep", type=float, default=0.0, help="Nghỉ giữa các cuộc họp (giây)")
    ap.add_argument("--out", help="Lưu kết quả chi tiết ra file JSON")
    args = ap.parse_args()

    all_cases = [c for c in discover_meetings(Path(args.data)) if c.has_expected_tasks]
    single = len(all_cases) == 1
    # Chấm 1 cuộc họp chỉ định rõ → cho chạy cả khi là dữ liệu giả lập (kiểm tra nhanh)
    cases = all_cases if single else select_cases(all_cases, args.include_synthetic)
    if not cases:
        raise SystemExit(f"Không tìm thấy cuộc họp nào có `expected_tasks.json` (đã gán nhãn) trong {args.data}")
    if args.transcript and len(cases) > 1:
        ap.error("--transcript chỉ dùng cho 1 cuộc họp; với nhiều cuộc họp hãy dùng --transcript-dir")
    warn_roster(cases)

    mode = "prompt_only" if args.no_members else args.member_mode
    t_path = Path(args.transcript) if args.transcript else None
    t_dir = Path(args.transcript_dir) if args.transcript_dir else None
    prefer_sp = args.use_speakers or args.no_speakers
    holder: dict[str, Any] = {}

    def llm_factory() -> Any:
        if "llm" not in holder:
            holder["llm"] = build_llm(args.provider, args.model, allow_fallback=args.allow_fallback)
        return holder["llm"]

    rows: list[dict[str, Any]] = []
    for idx, c in enumerate(cases):
        if idx > 0 and args.sleep > 0:
            time.sleep(args.sleep)
        src = resolve_transcript_source(c, t_path, t_dir, prefer_speakers=prefer_sp)
        raw = run_extraction(llm_factory, c, transcript_path=src, member_mode=mode, use_speakers=args.use_speakers)
        row = score_case(c, raw)
        rows.append(row)
        _print_single_report(row, c.members)

    label = rows[0]["model"] if rows else "?"
    agg = aggregate_extraction_runs(label, rows, meta={"model": label, "member_mode": mode, "use_speakers": args.use_speakers})

    if len(cases) > 1:
        print("\n=== TỔNG HỢP TOÀN BỘ TẬP DỮ LIỆU ===")
        print(f"  {agg['meetings_count']} cuộc họp | Đáp án {agg['expected_total']} | AI {agg['predicted_total']} | TP={agg['tp']} FP={agg['fp']} FN={agg['fn']}")
        print(f"  Micro : P={fmt_pct(agg['micro_precision'])} | R={fmt_pct(agg['micro_recall'])} | F1={fmt_pct(agg['micro_f1'])}{fmt_ci(agg['micro_f1_ci95'])}")
        print(f"  Macro : P={fmt_pct(agg['macro_precision'])} | R={fmt_pct(agg['macro_recall'])} | F1={fmt_pct(agg['macro_f1'])} ({agg['macro_meetings_count']} cuộc có đầu việc)")
        print(f"  Strict: P={fmt_pct(agg['strict_precision'])} | R={fmt_pct(agg['strict_recall'])} | F1={fmt_pct(agg['strict_f1'])}{fmt_ci(agg['strict_f1_ci95'])}")
        print(
            f"  Đúng người: {fmt_pct(agg['assignee_acc'])} | Đúng hạn (việc có hạn): {fmt_pct(agg['due_with_date_acc'])} | "
            f"Bịa hạn: {fmt_pct(agg['spurious_due_rate'])} | Câu gốc: {fmt_pct(agg['evidence_rate'])} | Thất bại: {len(agg['failed_meetings'])}"
        )

    if args.out:
        write_json(Path(args.out), rows[0] if len(rows) == 1 else agg)
        print(f"\nĐã lưu: {args.out}")


if __name__ == "__main__":
    main()
