"""Thư viện dùng chung cho toàn bộ kịch bản thực nghiệm Giai đoạn 7 (Chương 4 báo cáo).

Cung cấp:
  - Nạp cấu hình `backend/.env` mà KHÔNG đổi thư mục làm việc (`cwd`).
  - Đọc file dữ liệu bằng `utf-8-sig` (chịu được BOM do Notepad / PowerShell 5.1 thêm vào).
  - Khám phá, nạp và kiểm tra hợp lệ bộ dữ liệu trong `experiments/data/` (phân biệt LỖI chặn chạy
    và CẢNH BÁO), kèm cờ `synthetic` (dữ liệu TTS giả lập — mặc định loại khỏi số liệu Chương 4)
    và `annotated` (đáp án đã gán nhãn xong chưa).
  - Đọc bản ghi có nhãn người nói (`reference_speakers.txt` hoặc `.json` segments).
  - Tính WER thô, WER chuẩn hóa số (chuẩn hóa CẢ HAI phía), CER và tỉ lệ nhận đúng tên thành viên
    (chỉ đếm các từ VIẾT HOA trong bản chuẩn để không nhầm "miền nam", "an toàn" là tên).
  - Đo VRAM qua `nvidia-smi` (báo mức TĂNG so với nền), khoảng tin cậy bootstrap 95% theo cuộc họp.
  - Xuất kết quả ra JSON, CSV (`utf-8-sig` cho Excel) và bảng Markdown.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import csv
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import threading
import time
from typing import Any
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DEFAULT_DATA_DIR = ROOT / "experiments" / "data"
DEFAULT_RESULTS_DIR = ROOT / "experiments" / "results"
AUDIO_EXTS = (".wav", ".webm", ".mp3", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac", ".mp4")

BOOTSTRAP_SEED = 20261119  # hạt giống CỐ ĐỊNH → khoảng tin cậy tái lập được
BOOTSTRAP_SAMPLES = 2000

# Nhãn người nói hợp lệ ở đầu dòng: "Tên: nội dung" với phần tên ngắn
SPEAKER_HEAD_MAX_WORDS = 5
SPEAKER_HEAD_MAX_CHARS = 40


def setup_env() -> None:
    """Đưa `backend/` vào `sys.path` và bật UTF-8 cho stdout/stderr trên Windows."""
    b = str(BACKEND_DIR)
    if b not in sys.path:
        sys.path.insert(0, b)
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if reconf:
            try:
                reconf(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass


setup_env()

import jiwer  # noqa: E402
from app.ai.postprocess.name_matching import MemberInfo, match_name, strip_honorific  # noqa: E402
from app.ai.postprocess.text_utils import norm  # noqa: E402
from app.core.config import Settings  # noqa: E402


def load_backend_settings() -> Settings:
    """Đọc `backend/.env` mà không cần `os.chdir`."""
    env_file = BACKEND_DIR / ".env"
    return Settings(_env_file=env_file if env_file.exists() else None)


def read_text(path: Path) -> str:
    """Đọc file văn bản của bộ dữ liệu. `utf-8-sig` bỏ BOM nếu có (Notepad, PowerShell 5.1)."""
    return Path(path).read_text(encoding="utf-8-sig")


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


# =============================================================================
# 1. Chuẩn hóa văn bản & đo WER / CER / tỉ lệ nhận đúng tên thành viên
# =============================================================================

_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _under_100(n: int) -> str:
    if n < 10:
        return _DIGITS[n]
    if n < 20:
        u = n % 10
        return "mười" + ("" if u == 0 else " lăm" if u == 5 else " " + _DIGITS[u])
    t, u = divmod(n, 10)
    tail = "" if u == 0 else " mốt" if u == 1 else " tư" if u == 4 else " lăm" if u == 5 else " " + _DIGITS[u]
    return f"{_DIGITS[t]} mươi{tail}"


def _under_1000(n: int) -> str:
    if n < 100:
        return _under_100(n)
    h, r = divmod(n, 100)
    if r == 0:
        return f"{_DIGITS[h]} trăm"
    if r < 10:
        return f"{_DIGITS[h]} trăm lẻ {_DIGITS[r]}"
    return f"{_DIGITS[h]} trăm {_under_100(r)}"


def _padded_group(n: int) -> str:
    """Nhóm 3 chữ số đứng SAU nhóm lớn hơn: 5 → "không trăm lẻ năm", 26 → "không trăm hai mươi sáu"."""
    if n == 0:
        return ""
    if n < 10:
        return f"không trăm lẻ {_DIGITS[n]}"
    if n < 100:
        return f"không trăm {_under_100(n)}"
    return _under_1000(n)


def number_to_vi(n: int) -> str:
    """Đọc số nguyên tiếng Việt (tới hàng trăm triệu) theo MỘT cách đọc chuẩn duy nhất.

    Cách đọc chuẩn: "tư" (24 → hai mươi tư), "mốt", "lăm", "lẻ", "nghìn". Các biến thể tương đương
    ("bốn", "một", "linh", "ngàn") được quy về chuẩn này ở CẢ hai phía trong `normalize_tokens`.
    """
    if n < 0:
        return "âm " + number_to_vi(-n)
    if n < 1000:
        return _under_1000(n)
    if n >= 10**9:
        return str(n)
    millions, rest = divmod(n, 10**6)
    thousands, units = divmod(rest, 1000)
    parts: list[str] = []
    if millions:
        parts.append(f"{_under_1000(millions)} triệu")
    if thousands:
        parts.append(f"{_padded_group(thousands) if millions else _under_1000(thousands)} nghìn")
    if units:
        parts.append(_padded_group(units) if (millions or thousands) else _under_1000(units))
    return " ".join(parts)


# Biến đổi trên chuỗi gốc TRƯỚC khi bỏ dấu câu (cần dấu "/", ".", ",", "%", ":")
_PRE_NUMBER_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), r"\1 tháng \2 năm \3"),  # 25/11/2026
    (re.compile(r"\b(\d{1,2})/(\d{1,2})\b"), r"\1 tháng \2"),  # 25/11
    (re.compile(r"\b(\d{1,2})[h:](\d{2})\b"), r"\1 giờ \2"),  # 9h30, 9:30
    (re.compile(r"\b(\d{1,2})h\b"), r"\1 giờ"),  # 9h
    (re.compile(r"\b(\d{1,3}(?:\.\d{3})+)\b"), lambda m: m.group(1).replace(".", "")),  # 2.000 → 2000
    (re.compile(r"\b(\d+)[.,](\d+)\b"), r"\1 phẩy \2"),  # 3,5 → 3 phẩy 5
    (re.compile(r"(\d)\s*%"), r"\1 phần trăm"),  # 50% → 50 phần trăm
]

# Quy các cách đọc tương đương về một dạng (áp dụng cho CẢ bản chuẩn lẫn bản STT)
_WORD_CANON = {"ngàn": "nghìn", "mồng": "mùng"}
_PAIR_CANON = {("mươi", "bốn"): "tư", ("mươi", "một"): "mốt", ("trăm", "linh"): "lẻ", ("thứ", "bốn"): "tư"}


def normalize_tokens(text: str, numbers: bool = False) -> tuple[list[str], list[bool]]:
    """Tách từ đã chuẩn hóa + cờ "từ này viết hoa trong bản gốc" (dùng để đếm tên riêng).

    Chuẩn hóa: Unicode NFC, chữ thường, bỏ dấu câu. Khi `numbers=True`: đổi ngày "25/11", giờ "9h30",
    số "2.000", "3,5", "50%", chữ số → chữ đọc chuẩn, rồi quy các cách đọc tương đương về một dạng.
    Phép chuẩn hóa áp dụng đối xứng cho cả 2 phía nên không thiên vị bên nào.
    """
    t = unicodedata.normalize("NFC", text)
    if numbers:
        for pat, rep in _PRE_NUMBER_RULES:
            t = pat.sub(rep, t)
    t = re.sub(r"[^\w\s]", " ", t)
    tokens: list[str] = []
    caps: list[bool] = []
    for raw in t.split():
        if numbers and raw.isdigit():
            for w in number_to_vi(int(raw)).split():
                tokens.append(w)
                caps.append(False)
            continue
        tokens.append(raw.lower())
        caps.append(raw[:1].isupper())
    if numbers:
        tokens = [_WORD_CANON.get(w, w) for w in tokens]
        for i in range(1, len(tokens)):
            rep = _PAIR_CANON.get((tokens[i - 1], tokens[i]))
            if rep:
                tokens[i] = rep
    return tokens, caps


def normalize_for_wer(text: str, numbers: bool = False) -> str:
    """Chuẩn hóa câu trước khi tính WER (xem `normalize_tokens`)."""
    return " ".join(normalize_tokens(text, numbers)[0])


def member_name_tokens(members: list[MemberInfo]) -> set[str]:
    """Tập từ tên gọi (tên riêng + biệt danh đơn từ) dùng để đo tỉ lệ STT nghe đúng tên thành viên."""
    tokens: set[str] = set()
    for m in members:
        parts = normalize_for_wer(m.full_name, numbers=False).split()
        if parts:
            tokens.add(parts[-1])  # người Việt gọi nhau bằng chữ cuối của họ tên
        for nick in m.nicknames:
            cleaned = normalize_for_wer(strip_honorific(nick), numbers=False).split()
            if len(cleaned) == 1:
                tokens.add(cleaned[0])
    return {t for t in tokens if len(t) >= 2}


@dataclass
class WerMetrics:
    wer_raw: float
    wer_norm: float
    cer_norm: float
    hits: int
    substitutions: int
    deletions: int
    insertions: int
    ref_words: int
    raw_errors: int
    raw_ref_words: int
    name_hits: int = 0
    name_total: int = 0

    @property
    def name_accuracy(self) -> float | None:
        return (self.name_hits / self.name_total) if self.name_total > 0 else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "wer_raw": round(self.wer_raw, 4),
            "wer_norm": round(self.wer_norm, 4),
            "cer_norm": round(self.cer_norm, 4),
            "hits": self.hits,
            "substitutions": self.substitutions,
            "deletions": self.deletions,
            "insertions": self.insertions,
            "ref_words": self.ref_words,
            "raw_errors": self.raw_errors,
            "raw_ref_words": self.raw_ref_words,
            "name_hits": self.name_hits,
            "name_total": self.name_total,
            "name_accuracy": round(self.name_accuracy, 4) if self.name_accuracy is not None else None,
        }


def compute_wer_metrics(ref: str, hyp: str, members: list[MemberInfo] | None = None) -> WerMetrics:
    """Tính WER thô, WER chuẩn hóa số, CER và độ chính xác nhận dạng tên thành viên.

    Tên thành viên: chỉ đếm vị trí trong bản CHUẨN mà từ đó là tên gọi của thành viên VÀ được viết
    hoa ở bản gốc ("Nam" là tên, "miền nam" thì không). Bản chuẩn vì vậy phải giữ chữ hoa tên riêng.
    """
    r_raw, h_raw = normalize_for_wer(ref, numbers=False), normalize_for_wer(hyp, numbers=False)
    r_tokens, r_caps = normalize_tokens(ref, numbers=True)
    r_norm, h_norm = " ".join(r_tokens), normalize_for_wer(hyp, numbers=True)

    o_raw = jiwer.process_words(r_raw, h_raw)
    o_norm = jiwer.process_words(r_norm, h_norm)
    cer = float(jiwer.cer(r_norm, h_norm)) if r_norm else 0.0

    name_hits, name_total = 0, 0
    if members:
        targets = member_name_tokens(members)
        if targets:
            ref_toks = o_norm.references[0]
            matched_idx: set[int] = set()
            for chunk in o_norm.alignments[0]:
                if chunk.type == "equal":
                    matched_idx.update(range(chunk.ref_start_idx, chunk.ref_end_idx))
            for idx, tok in enumerate(ref_toks):
                if tok in targets and idx < len(r_caps) and r_caps[idx]:
                    name_total += 1
                    if idx in matched_idx:
                        name_hits += 1

    raw_n = o_raw.hits + o_raw.substitutions + o_raw.deletions
    norm_n = o_norm.hits + o_norm.substitutions + o_norm.deletions
    return WerMetrics(
        wer_raw=float(o_raw.wer),
        wer_norm=float(o_norm.wer),
        cer_norm=cer,
        hits=o_norm.hits,
        substitutions=o_norm.substitutions,
        deletions=o_norm.deletions,
        insertions=o_norm.insertions,
        ref_words=norm_n,
        raw_errors=o_raw.substitutions + o_raw.deletions + o_raw.insertions,
        raw_ref_words=raw_n,
        name_hits=name_hits,
        name_total=name_total,
    )


# =============================================================================
# 2. Nạp & kiểm tra hợp lệ bộ dữ liệu cuộc họp (1 cuộc hoặc cả thư mục data/)
# =============================================================================


@dataclass
class MeetingCase:
    """Một cuộc họp trong bộ dữ liệu thực nghiệm (`experiments/data/<meeting_id>/`)."""

    meeting_id: str
    folder: Path
    meeting_date: date | None
    audio_path: Path | None
    reference_path: Path | None
    reference_speakers_path: Path | None
    expected_tasks_path: Path | None
    echo_eval_path: Path | None
    members: list[MemberInfo] = field(default_factory=list)
    expected_tasks: list[dict[str, Any]] = field(default_factory=list)
    source: str = "audio"  # audio | online | upload | tts
    synthetic: bool = False  # dữ liệu giả lập (TTS) → mặc định KHÔNG đưa vào số liệu Chương 4
    annotated: bool = True  # False = template chưa gán nhãn xong (xuất từ MeetFlow) → bỏ qua
    roster_declared: bool = True  # False = danh sách thành viên suy ra từ đáp án (có rủi ro rò rỉ)
    guests: list[str] = field(default_factory=list)  # người nói không có tài khoản (khách)

    @property
    def has_audio(self) -> bool:
        return self.audio_path is not None and self.audio_path.exists()

    @property
    def has_reference(self) -> bool:
        return self.reference_path is not None and self.reference_path.exists() and bool(read_text(self.reference_path).strip())

    @property
    def has_speaker_reference(self) -> bool:
        p = self.reference_speakers_path
        return p is not None and p.exists() and bool(read_text(p).strip())

    @property
    def online_segments_path(self) -> Path | None:
        p = self.folder / "online_segments.json"
        return p if p.exists() else None

    @property
    def has_online_segments(self) -> bool:
        """Có `online_segments.json` THẬT (ít nhất 1 câu mang `speaker_id`)."""
        p = self.online_segments_path
        if p is None:
            return False
        try:
            data = read_json(p)
        except (json.JSONDecodeError, OSError):
            return False
        segs = data.get("segments", []) if isinstance(data, dict) else data
        return any(isinstance(s, dict) and s.get("speaker_id") is not None for s in segs)

    @property
    def has_expected_tasks(self) -> bool:
        return (
            self.expected_tasks_path is not None
            and self.expected_tasks_path.exists()
            and self.meeting_date is not None
            and self.annotated
        )


def _find_audio_file(folder: Path) -> Path | None:
    for ext in AUDIO_EXTS:
        p = folder / f"meeting{ext}"
        if p.exists():
            return p
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            return p
    return None


def split_speaker_head(line: str) -> tuple[str, str] | None:
    """`"Nguyễn Văn Nam: nội dung"` → ("Nguyễn Văn Nam", "nội dung"); không có nhãn ngắn hợp lệ → None."""
    head, sep, rest = line.partition(":")
    head, rest = head.strip(), rest.strip()
    if not sep or not rest or not head:
        return None
    if len(head) > SPEAKER_HEAD_MAX_CHARS or len(head.split()) > SPEAKER_HEAD_MAX_WORDS:
        return None
    return head, rest


def _parse_members(answer: dict[str, Any], speaker_ref_path: Path | None) -> tuple[list[MemberInfo], bool]:
    """Đọc danh sách thành viên + biệt danh từ `expected_tasks.json` → (members, roster_declared).

    Tương thích ngược: file cũ không có `members` → suy ra từ tên người làm trong `tasks` và nhãn
    người nói. Cách này RÒ RỈ đáp án (danh sách = đúng tập người được giao việc, không có người
    "gây nhiễu") nên `roster_declared=False` để các script cảnh báo.
    """
    raw_members = answer.get("members")
    if isinstance(raw_members, list) and raw_members:
        out: list[MemberInfo] = []
        for idx, m in enumerate(raw_members, 1):
            if isinstance(m, str):
                out.append(MemberInfo(idx, m.strip(), []))
            elif isinstance(m, dict) and m.get("full_name"):
                uid = int(m.get("id") or idx)
                nicks = [str(x).strip() for x in (m.get("nicknames") or []) if str(x).strip()]
                out.append(MemberInfo(uid, str(m["full_name"]).strip(), nicks))
        if out:
            return out, True

    names: set[str] = set()
    for t in answer.get("tasks") or []:
        if t.get("assignee"):
            names.add(str(t["assignee"]).strip())
    if speaker_ref_path and speaker_ref_path.exists():
        for line in read_text(speaker_ref_path).splitlines():
            sp = split_speaker_head(line)
            if sp:
                names.add(sp[0])
    return [MemberInfo(i, name, []) for i, name in enumerate(sorted(names), 1)], False


def build_stt_prompt(members: list[MemberInfo]) -> str | None:
    """Tạo `initial_prompt` giống hệt production (`app/workers/jobs.py:build_initial_prompt`)."""
    if not members:
        return None
    parts = []
    for m in members:
        nick = f" ({', '.join(m.nicknames)})" if m.nicknames else ""
        parts.append(f"{m.full_name}{nick}")
    return ("Cuộc họp nhóm. Thành viên: " + ", ".join(parts) + ".")[:800]


def load_meeting(folder: Path) -> MeetingCase:
    """Nạp toàn bộ thông tin của 1 thư mục cuộc họp."""
    folder = folder.resolve()
    ref = folder / "reference.txt"
    ref_sp = folder / "reference_speakers.txt"
    exp = folder / "expected_tasks.json"
    echo = folder / "echo_eval.json"

    answer: dict[str, Any] = {}
    meeting_date: date | None = None
    if exp.exists():
        answer = read_json(exp)
        if answer.get("meeting_date"):
            meeting_date = date.fromisoformat(str(answer["meeting_date"]))

    members, declared = _parse_members(answer, ref_sp if ref_sp.exists() else None)
    source = str(answer.get("source") or ("online" if ref_sp.exists() else "audio"))
    return MeetingCase(
        meeting_id=folder.name,
        folder=folder,
        meeting_date=meeting_date,
        audio_path=_find_audio_file(folder),
        reference_path=ref if ref.exists() else None,
        reference_speakers_path=ref_sp if ref_sp.exists() else None,
        expected_tasks_path=exp if exp.exists() else None,
        echo_eval_path=echo if echo.exists() else None,
        members=members,
        expected_tasks=list(answer.get("tasks") or []),
        source=source,
        synthetic=bool(answer.get("synthetic", False)) or source == "tts",
        annotated=bool(answer.get("annotated", True)),
        roster_declared=declared,
        guests=[str(g).strip() for g in (answer.get("guests") or []) if str(g).strip()],
    )


def _is_meeting_folder(p: Path) -> bool:
    if not p.is_dir():
        return False
    return any((p / f).exists() for f in ("expected_tasks.json", "reference.txt", "reference_speakers.txt", "echo_eval.json"))


def discover_meetings(path: Path) -> list[MeetingCase]:
    """Nhận 1 thư mục cuộc họp HOẶC thư mục cha chứa nhiều cuộc họp (`experiments/data/`)."""
    path = path.resolve()
    if _is_meeting_folder(path):
        return [load_meeting(path)]
    if not path.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục dữ liệu: {path}")
    found = [
        load_meeting(sub)
        for sub in sorted(path.iterdir())
        if sub.is_dir() and not sub.name.startswith(("_", ".")) and _is_meeting_folder(sub)
    ]
    if not found:
        raise FileNotFoundError(f"Không tìm thấy cuộc họp nào trong: {path}")
    return found


def select_cases(cases: list[MeetingCase], include_synthetic: bool = False, verbose: bool = True) -> list[MeetingCase]:
    """Loại cuộc họp giả lập (`"synthetic": true`, VD. TTS) khỏi số liệu Chương 4 trừ khi `--include-synthetic`."""
    if include_synthetic:
        return list(cases)
    kept = [c for c in cases if not c.synthetic]
    dropped = [c.meeting_id for c in cases if c.synthetic]
    if dropped and verbose:
        print(f"Bỏ qua {len(dropped)} cuộc họp giả lập (synthetic): {', '.join(dropped)} — thêm --include-synthetic nếu muốn chạy thử.")
    return kept


def warn_roster(cases: list[MeetingCase]) -> None:
    """Cảnh báo khi danh sách thành viên suy ra từ đáp án (không khai báo `members`)."""
    bad = [c.meeting_id for c in cases if not c.roster_declared]
    if bad:
        print(
            "CẢNH BÁO: các cuộc họp sau KHÔNG khai báo `members` → danh sách thành viên bị suy ra từ đáp án "
            f"(rò rỉ, không có người gây nhiễu): {', '.join(bad)}. Hãy khai báo đúng danh sách nhóm thật."
        )


def resolve_member(name: str | None, members: list[MemberInfo]) -> MemberInfo | None:
    """Tìm thành viên khớp duy nhất với `name` (khớp họ tên trước, rồi tới `match_name`)."""
    if not name or not name.strip():
        return None
    cleaned = norm(name)
    for m in members:
        if norm(m.full_name) == cleaned:
            return m
    res = match_name(name, members)
    if res.user_id is not None:
        return next((m for m in members if m.user_id == res.user_id), None)
    return None


def resolve_member_exact(name: str | None, members: list[MemberInfo]) -> MemberInfo | None:
    """Khớp CHÍNH XÁC theo họ tên hoặc biệt danh đã khai báo (không mờ) — dùng để kiểm tra đáp án."""
    if not name or not name.strip():
        return None
    cleaned = norm(strip_honorific(name))
    for m in members:
        aliases = {norm(m.full_name)} | {norm(strip_honorific(n)) for n in m.nicknames}
        if cleaned in aliases or norm(name) in aliases:
            return m
    return None


def parse_transcript_segments(
    source: Path,
    members: list[MemberInfo] | None = None,
    parse_speakers: bool = False,
    speaker_format: bool | None = None,
) -> list[dict[str, Any]]:
    """Đọc bản ghi từ `.json` (segments STT / Online Meeting) hoặc `.txt` thành danh sách segments.

    - `speaker_format=True` (mặc định cho file `*_speakers.txt`): MỌI dòng dạng `"Tên: nội dung"` với
      phần tên ngắn đều được tách nhãn khỏi nội dung — kể cả tên không khớp thành viên (khách) — để
      nhánh "không nhãn người nói" không bị lộ tên người nói qua nội dung. Tên khớp thành viên →
      `speaker` (họ tên chuẩn) + `speaker_id`; không khớp → `speaker` = nhãn gốc, `speaker_id` = None.
    - File thường (`reference.txt`) với `parse_speakers=True`: chỉ tách khi phần trước dấu `:` khớp
      một thành viên, để câu như "Chốt lại: Lan làm slide" KHÔNG bị tách nhầm.
    """
    members = members or []
    if source.suffix.lower() == ".json":
        data = read_json(source)
        raw_segs = data["segments"] if isinstance(data, dict) and "segments" in data else data
        segments: list[dict[str, Any]] = []
        for s in raw_segs:
            seg = dict(s)
            seg["text"] = str(seg.get("text", "")).strip()
            if not seg["text"]:
                continue
            if parse_speakers and seg.get("speaker") and seg.get("speaker_id") is None and members:
                if (m := resolve_member(str(seg["speaker"]), members)) is not None:
                    seg["speaker"], seg["speaker_id"] = m.full_name, m.user_id
            segments.append(seg)
        return segments

    if speaker_format is None:
        speaker_format = source.name.endswith("_speakers.txt")
    out: list[dict[str, Any]] = []
    for line in read_text(source).splitlines():
        line = line.strip()
        if not line:
            continue
        if speaker_format or parse_speakers:
            sp = split_speaker_head(line)
            if sp is not None:
                head, rest = sp
                m = resolve_member(head, members)
                if m is not None:
                    out.append({"start": None, "end": None, "text": rest, "speaker": m.full_name, "speaker_id": m.user_id})
                    continue
                if speaker_format:
                    out.append({"start": None, "end": None, "text": rest, "speaker": head, "speaker_id": None})
                    continue
        out.append({"start": None, "end": None, "text": line})
    return out


def validate_meeting(folder: Path) -> tuple[list[str], list[str]]:
    """Kiểm tra 1 thư mục cuộc họp → (LỖI, CẢNH BÁO). Có LỖI thì không nên chạy thực nghiệm."""
    errors: list[str] = []
    warnings: list[str] = []
    if not _is_meeting_folder(folder):
        return ["Thư mục không chứa file dữ liệu chuẩn nào (reference.txt / expected_tasks.json / echo_eval.json)"], []

    exp = folder / "expected_tasks.json"
    if exp.exists():
        try:
            answer = read_json(exp)
        except json.JSONDecodeError as e:
            return [f"expected_tasks.json lỗi JSON: {e}"], []
        md = answer.get("meeting_date")
        if not md:
            errors.append("expected_tasks.json thiếu trường `meeting_date` (YYYY-MM-DD)")
        else:
            try:
                date.fromisoformat(str(md))
            except ValueError:
                errors.append(f"`meeting_date` không đúng định dạng YYYY-MM-DD: {md!r}")
        if not isinstance(answer.get("tasks"), list):
            errors.append("expected_tasks.json thiếu mảng `tasks`")
        else:
            for idx, t in enumerate(answer["tasks"], 1):
                if not t.get("task"):
                    errors.append(f"tasks[{idx}] thiếu nội dung `task`")
                due = t.get("due_date")
                if due:
                    try:
                        date.fromisoformat(str(due))
                    except ValueError:
                        errors.append(f"tasks[{idx}].due_date sai định dạng YYYY-MM-DD: {due!r}")

    case = load_meeting(folder)
    if not case.annotated:
        warnings.append("`annotated: false` — đáp án CHƯA gán nhãn xong, cuộc họp bị bỏ qua ở TN2/TN3/TN4A")
    elif exp.exists() and not case.expected_tasks:
        warnings.append("`tasks` rỗng — cuộc họp không có đầu việc nào (mọi đầu việc AI đưa ra sẽ tính là FP)")
    if case.synthetic:
        warnings.append("`synthetic: true` — dữ liệu giả lập, mặc định bị loại khỏi số liệu Chương 4")
    if exp.exists() and not case.roster_declared:
        warnings.append("Không khai báo `members` → danh sách thành viên bị suy ra từ đáp án (rò rỉ). Hãy khai báo danh sách nhóm thật")

    seen_ids: set[int] = set()
    for m in case.members:
        if m.user_id in seen_ids:
            errors.append(f"Trùng `members.id = {m.user_id}` ({m.full_name})")
        seen_ids.add(m.user_id)

    if case.roster_declared:
        for idx, t in enumerate(case.expected_tasks, 1):
            who = t.get("assignee")
            if who and resolve_member_exact(str(who), case.members) is None:
                fuzzy = resolve_member(str(who), case.members)
                if fuzzy is not None:
                    warnings.append(f"tasks[{idx}].assignee {who!r} không khớp chính xác tên/biệt danh, đang hiểu là {fuzzy.full_name!r}")
                else:
                    warnings.append(f"tasks[{idx}].assignee {who!r} không có trong `members` → coi là người ngoài nhóm (F20)")

    if case.reference_speakers_path and case.reference_speakers_path.exists():
        guests = {norm(g) for g in case.guests}
        for line_no, raw in enumerate(read_text(case.reference_speakers_path).splitlines(), 1):
            line = raw.strip()
            if not line:
                continue
            sp = split_speaker_head(line)
            if sp is None:
                errors.append(f"reference_speakers.txt dòng {line_no}: thiếu tiền tố 'Tên: nội dung'")
            elif resolve_member(sp[0], case.members) is None and norm(sp[0]) not in guests:
                errors.append(
                    f"reference_speakers.txt dòng {line_no}: người nói {sp[0]!r} không khớp `members` "
                    "(khai báo vào `members`, hoặc vào `guests` nếu là khách không có tài khoản)"
                )

    if case.online_segments_path:
        try:
            data = read_json(case.online_segments_path)
            segs = data.get("segments", []) if isinstance(data, dict) else data
            ids = {s.get("speaker_id") for s in segs if isinstance(s, dict) and s.get("speaker_id") is not None}
            missing = ids - {m.user_id for m in case.members}
            if missing:
                errors.append(f"online_segments.json có speaker_id {sorted(missing)} không nằm trong `members.id` (đừng đánh số lại id)")
        except json.JSONDecodeError as e:
            errors.append(f"online_segments.json lỗi JSON: {e}")

    if case.echo_eval_path:
        try:
            raw = read_json(case.echo_eval_path)
            segs = raw.get("segments", []) if isinstance(raw, dict) else raw
            unl = sum(1 for s in segs if not isinstance(s.get("is_echo"), bool))
            if unl:
                warnings.append(f"echo_eval.json còn {unl}/{len(segs)} câu chưa gán nhãn `is_echo` (true/false) → bị bỏ qua ở TN4B")
        except json.JSONDecodeError as e:
            errors.append(f"echo_eval.json lỗi JSON: {e}")

    if case.reference_path and case.reference_path.exists():
        txt = read_text(case.reference_path)
        if not txt.strip():
            warnings.append("reference.txt đang trống (chưa gõ bản ghi chuẩn) → chưa chạy được TN1")
        elif not any(ch.isupper() for ch in txt):
            warnings.append("reference.txt không có chữ hoa → không đo được tỉ lệ đúng tên (tên riêng phải viết hoa)")
    if not case.has_audio:
        warnings.append("Chưa có file âm thanh (meeting.wav / .webm / .mp3...) — chỉ chạy được TN2/TN4, chưa chạy được TN1/TN3")
    return errors, warnings


# =============================================================================
# 3. Thống kê: khoảng tin cậy bootstrap 95% theo cuộc họp
# =============================================================================


def bootstrap_ci(
    rows: Sequence[dict[str, Any]],
    stat: Callable[[Sequence[dict[str, Any]]], float | None],
    n_boot: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = 0.05,
) -> list[float] | None:
    """Khoảng tin cậy percentile (1-alpha) bằng cách lấy mẫu LẠI CÁC CUỘC HỌP có hoàn lại.

    `stat(rows)` tính chỉ số gộp (VD. Micro F1) trên một tập cuộc họp. Ít hơn 2 cuộc họp → None.
    """
    n = len(rows)
    if n < 2:
        return None
    rng = random.Random(seed)
    vals: list[float] = []
    for _ in range(n_boot):
        sample = [rows[rng.randrange(n)] for _ in range(n)]
        v = stat(sample)
        if v is not None:
            vals.append(float(v))
    if len(vals) < max(10, n_boot // 10):
        return None
    vals.sort()
    lo = vals[int((alpha / 2) * (len(vals) - 1))]
    hi = vals[int((1 - alpha / 2) * (len(vals) - 1))]
    return [round(lo, 4), round(hi, 4)]


def paired_bootstrap_delta(
    rows_a: Sequence[dict[str, Any]],
    rows_b: Sequence[dict[str, Any]],
    stat: Callable[[Sequence[dict[str, Any]]], float | None],
    key: str = "meeting_id",
    n_boot: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Δ = stat(B) − stat(A) trên CÙNG tập cuộc họp, kèm khoảng tin cậy bootstrap ghép cặp."""
    by_a = {r[key]: r for r in rows_a}
    by_b = {r[key]: r for r in rows_b}
    ids = sorted(set(by_a) & set(by_b))
    a = [by_a[i] for i in ids]
    b = [by_b[i] for i in ids]
    sa, sb = stat(a), stat(b)
    point = round(sb - sa, 4) if sa is not None and sb is not None else None
    ci: list[float] | None = None
    if len(ids) >= 2 and point is not None:
        rng = random.Random(seed)
        vals: list[float] = []
        for _ in range(n_boot):
            idx = [rng.randrange(len(ids)) for _ in ids]
            va, vb = stat([a[i] for i in idx]), stat([b[i] for i in idx])
            if va is not None and vb is not None:
                vals.append(vb - va)
        if len(vals) >= max(10, n_boot // 10):
            vals.sort()
            ci = [round(vals[int(0.025 * (len(vals) - 1))], 4), round(vals[int(0.975 * (len(vals) - 1))], 4)]
    return {"delta": point, "ci95": ci, "meetings": len(ids)}


# =============================================================================
# 4. Đo VRAM GPU (qua nvidia-smi — dùng chung cho CTranslate2 / PyTorch / Ollama)
# =============================================================================


def query_gpu_memory_mb() -> int | None:
    """VRAM đang dùng (MB) của GPU đầu tiên — tính TOÀN thiết bị (cả desktop, trình duyệt, Ollama...)."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        ).strip()
        first = out.splitlines()[0].strip() if out else ""
        return int(first) if first.isdigit() else None
    except Exception:  # noqa: BLE001
        return None


class VRAMMonitor:
    """Theo dõi VRAM trong khối `with VRAMMonitor() as vm:` (lấy mẫu mỗi 150ms).

    Chỉ số nên báo cáo là `delta_mb` (đỉnh − nền lúc bắt đầu) vì `nvidia-smi` đo toàn thiết bị.
    """

    def __init__(self, interval_sec: float = 0.15) -> None:
        self.interval = interval_sec
        self.baseline_mb: int | None = None
        self.peak_mb: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def delta_mb(self) -> int | None:
        if self.baseline_mb is None or self.peak_mb is None:
            return None
        return max(0, self.peak_mb - self.baseline_mb)

    def _poll(self) -> None:
        while not self._stop.is_set():
            v = query_gpu_memory_mb()
            if v is not None and (self.peak_mb is None or v > self.peak_mb):
                self.peak_mb = v
            self._stop.wait(self.interval)

    def __enter__(self) -> VRAMMonitor:
        self.baseline_mb = query_gpu_memory_mb()
        self.peak_mb = self.baseline_mb
        if self.baseline_mb is not None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._poll, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        v = query_gpu_memory_mb()
        if v is not None and (self.peak_mb is None or v > self.peak_mb):
            self.peak_mb = v


# =============================================================================
# 5. Xuất báo cáo nhất quán (JSON, CSV cho Excel, Markdown cho báo cáo Chương 4)
# =============================================================================


def fmt_pct(v: float | None, digits: int = 1) -> str:
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def fmt_ci(ci: Sequence[float] | None, digits: int = 1) -> str:
    return "" if not ci else f" [{ci[0] * 100:.{digits}f}–{ci[1] * 100:.{digits}f}]"


def safe_div(a: float, b: float) -> float | None:
    return (a / b) if b else None


def rnd(v: float | None, digits: int = 4) -> float | None:
    return None if v is None else round(v, digits)


def slugify_model(name: str) -> str:
    """Tên mô hình → tên thư mục an toàn trên Windows (VD. `vinai/PhoWhisper-small` → `vinai__PhoWhisper-small`)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "__", name.strip()).strip("_")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    """Ghi CSV với BOM (`utf-8-sig`) để Excel trên Windows hiển thị chuẩn tiếng Việt có dấu."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines) + "\n"


def write_markdown(path: Path, title: str, sections: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [f"# {title}\n", f"_Tự động sinh bởi bộ script thực nghiệm GĐ7 ({time.strftime('%d/%m/%Y %H:%M')})._\n"]
    for heading, body in sections:
        parts.append(f"## {heading}\n\n{body.strip()}\n")
    path.write_text("\n".join(parts), encoding="utf-8")
