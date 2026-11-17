"""F15 — Ghép tên người được nhắc trong cuộc họp với tài khoản thành viên nhóm.

LLM chỉ trả về CHỮ ("Nam", "anh Nam", "chị Lan"). Việc tìm ra đó là tài khoản nào
do code Python làm (không dùng AI) → kết quả ổn định, giải thích được, test được.

So khớp theo 3 mức, mức trên thắng mức dưới:
    1. exact      — trùng hẳn (có dấu)          "Lan"  ↔ "Lan"
    2. no_accent  — trùng khi bỏ dấu             "Nam"  ↔ "Năm"  (Whisper nghe sai dấu)
    3. fuzzy      — gần giống (rapidfuzz ≥ 85)   "Min"  ↔ "Minh" (Whisper nghe thiếu chữ)

Hai thành viên cùng đạt mức cao nhất (vd. nhóm có 2 bạn tên Nam) → KHÔNG tự chọn,
đánh dấu "ambiguous" để người dùng chọn ở màn hình duyệt.
"""

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.ai.postprocess.text_utils import norm, norm_no_accent

FUZZY_THRESHOLD = 85

# Từ xưng hô đứng trước tên: "anh Nam" → "Nam"
HONORIFICS = {"anh", "chị", "em", "bạn", "cô", "chú", "bác", "thầy", "ông", "bà", "cậu", "dì"}

# Người nói tự nhận việc ("để em làm", "phần này anh lo"). Bản ghi không có thông tin
# ai nói câu nào → KHÔNG đoán, để trống người làm cho người dùng chọn khi duyệt.
SELF_WORDS = {"tôi", "mình", "tớ", "tui", "tao", "em", "anh", "chị", "cháu", "con", "người nói", "bản thân"}

# Giao cho cả nhóm → không có 1 người chịu trách nhiệm cụ thể
GROUP_WORDS = {"cả nhóm", "mọi người", "tất cả", "tất cả mọi người", "cả team", "team", "nhóm", "các bạn", "chúng ta", "chúng mình"}


@dataclass
class MemberInfo:
    user_id: int
    full_name: str
    nicknames: list[str] = field(default_factory=list)


@dataclass
class NameMatch:
    user_id: int | None
    method: str  # exact | no_accent | fuzzy | ambiguous | self | group | none
    score: int = 0
    candidates: list[int] = field(default_factory=list)  # khi ambiguous: các tài khoản có thể đúng


def strip_honorific(name: str) -> str:
    """"anh Nam" → "nam"; "em" (đứng một mình) giữ nguyên."""
    words = norm(name).split()
    if len(words) > 1 and words[0] in HONORIFICS:
        words = words[1:]
    return " ".join(words)


def split_assignees(raw: str) -> list[str]:
    """"Lan và Minh" → ["Lan", "Minh"]. Mỗi người sẽ thành 1 đầu việc riêng."""
    parts = re.split(r"\s*(?:,|;|/|&|\+)\s*|\s+(?:và|với|cùng)\s+", raw.strip())
    return [p.strip() for p in parts if p and p.strip()]


def _declared(m: MemberInfo) -> set[str]:
    """Cách gọi do người dùng KHAI BÁO: họ tên đầy đủ và biệt danh (có và không có xưng hô)."""
    out = {norm(m.full_name)}
    for nick in m.nicknames:
        out.add(norm(nick))
        out.add(strip_honorific(nick))
    out.discard("")
    return out


def _aliases(m: MemberInfo) -> set[str]:
    """Mọi cách gọi một thành viên = khai báo + tên gọi suy ra (chữ cuối của họ tên)."""
    out = _declared(m)
    words = norm(m.full_name).split()
    if words:
        out.add(words[-1])  # người Việt gọi nhau bằng chữ cuối của họ tên
    return out


def _score(raw: str, m: MemberInfo) -> tuple[int, str]:
    """Điểm khớp cao nhất giữa `raw` (đã bỏ xưng hô) và một thành viên.

    Biệt danh khai báo được điểm cao hơn tên suy ra 2 điểm: nhóm có 2 bạn tên Nam,
    bạn nào đặt biệt danh "Nam" thì chữ "Nam" trong cuộc họp thuộc về bạn đó.
    """
    declared, aliases = _declared(m), _aliases(m)
    if raw in aliases:
        return (100 if raw in declared else 98), "exact"
    raw_na = norm_no_accent(raw)
    aliases_na = {norm_no_accent(a) for a in aliases}
    if raw_na in aliases_na:
        return (95 if raw_na in {norm_no_accent(a) for a in declared} else 93), "no_accent"
    best = max((fuzz.ratio(raw_na, a) for a in aliases_na), default=0)
    # "Văn Nam" ↔ "Nguyễn Văn Nam": so theo tập từ khi tên được gọi có từ 2 chữ trở lên
    if len(raw_na.split()) >= 2:
        best = max(best, fuzz.token_set_ratio(raw_na, norm_no_accent(m.full_name)) - 5)
    if best >= FUZZY_THRESHOLD:
        return min(int(best), 92), "fuzzy"
    return 0, "none"


def match_name(raw: str | None, members: list[MemberInfo]) -> NameMatch:
    if not raw or not raw.strip():
        return NameMatch(None, "none")
    plain = norm(raw)
    if plain in SELF_WORDS:
        # Ngoại lệ: nhóm có bạn tên "Anh" (Nguyễn Tuấn Anh) và LLM viết hoa "Anh" → là tên riêng
        is_member_name = raw.strip()[:1].isupper() and any(plain in _aliases(m) for m in members)
        if not is_member_name:
            return NameMatch(None, "self")
    if plain in GROUP_WORDS:
        return NameMatch(None, "group")

    name = strip_honorific(raw)
    scored = [(s, how, m.user_id) for m in members for s, how in [_score(name, m)] if s > 0]
    if not scored:
        return NameMatch(None, "none")
    top = max(s for s, _, _ in scored)
    winners = [(how, uid) for s, how, uid in scored if s == top]
    if len(winners) > 1:
        return NameMatch(None, "ambiguous", top, [uid for _, uid in winners])
    how, uid = winners[0]
    return NameMatch(uid, how, top)
