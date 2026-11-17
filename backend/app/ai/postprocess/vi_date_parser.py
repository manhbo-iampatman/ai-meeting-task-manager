"""F16 — Đổi hạn chót nói bằng lời ("thứ Sáu tuần sau") thành ngày cụ thể.

Mọi phép tính lấy NGÀY HỌP làm mốc (không phải ngày bấm nút tóm tắt): ghi âm họp
hôm 16/11 mà 3 ngày sau mới tải lên thì "ngày mai" vẫn phải là 17/11.

Vì sao tự viết luật mà không dùng thư viện `dateparser`? Thử thật thì `dateparser`
không hiểu "thứ sáu tuần này", "3 ngày nữa", "cuối tháng" (trả về None). Nên luật
tiếng Việt viết tay là chính, `dateparser` chỉ là lưới đỡ cuối cùng.

Thứ tự ưu tiên khi một câu có nhiều cách hiểu:
    ngày tuyệt đối (25/11) > thứ trong tuần > số ngày tương đối > cách nói mơ hồ

Kết quả có cờ `approximate` = hệ thống phải ƯỚC LƯỢNG theo quy ước (vd. "cuối tuần"
= Chủ nhật) → giao diện nhắc người dùng kiểm tra lại khi duyệt.
"""

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass
class DueResult:
    date: date | None
    approximate: bool = False
    rule: str = ""  # luật nào đã khớp — để giải thích / gỡ lỗi


WEEKDAY_WORDS = {"hai": 0, "ba": 1, "tư": 2, "năm": 3, "sáu": 4, "bảy": 5, "bẩy": 5}
UNITS = {"một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5, "lăm": 5, "nhăm": 5,
         "sáu": 6, "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9}
MONTH_WORDS = {"giêng": 1, "chạp": 12}

NEXT = r"(?:sau|tới|tiếp theo)"


# ---------- Bước 1: chuẩn hóa chuỗi ----------


def _mark_weekdays(s: str) -> str:
    """"thứ sáu", "thứ 6", "t6", "chủ nhật" → ký hiệu @wd4 / @wd6 (0 = thứ Hai)."""

    def by_word(m: re.Match) -> str:
        w = m.group(1)
        idx = WEEKDAY_WORDS[w] if w in WEEKDAY_WORDS else int(w) - 2
        return f" @wd{idx} "

    s = re.sub(r"\bthứ\s*(hai|ba|tư|năm|sáu|bảy|bẩy|[2-7])\b", by_word, s)
    s = re.sub(r"\bt([2-7])\b", lambda m: f" @wd{int(m.group(1)) - 2} ", s)
    return re.sub(r"\b(?:chủ\s*nhật|cn)\b", " @wd6 ", s)


def _words_to_digits(s: str) -> str:
    """"hai mươi lăm" → "25", "mười một" → "11", "ba" → "3".

    Gọi SAU khi đã đánh dấu thứ trong tuần và năm, nên "thứ năm" hay "năm 2026"
    không bị hiểu nhầm thành số 5.
    """
    tokens = s.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        nxt2 = tokens[i + 2] if i + 2 < len(tokens) else ""
        if t == "mười":  # 10–19
            if nxt in UNITS:
                out.append(str(10 + UNITS[nxt]))
                i += 2
            else:
                out.append("10")
                i += 1
        elif t in UNITS and nxt == "mươi":  # 20–99
            if nxt2 in UNITS:
                out.append(str(UNITS[t] * 10 + UNITS[nxt2]))
                i += 3
            else:
                out.append(str(UNITS[t] * 10))
                i += 2
        elif t in UNITS and t not in ("mốt", "lăm", "nhăm"):  # 3 từ này chỉ là số khi đứng sau "mươi" / "mười"
            out.append(str(UNITS[t]))
            i += 1
        else:
            out.append(t)
            i += 1
    return " ".join(out)


def normalize(text: str) -> str:
    s = unicodedata.normalize("NFC", text).lower()
    s = re.sub(r"[,;!?()\"“”]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _mark_weekdays(s)
    # "ngày mốt" / "ngày kia" phải xử lý trước khi "mốt" bị coi là số 1
    # ("hai mươi mốt" = 21 thì giữ nguyên, nhờ điều kiện "không đứng sau mươi")
    s = re.sub(r"(?<!mươi )\b(?:ngày\s+)?(?:mốt|kia)\b", " @plus2 ", s)
    # Giữ "năm" (year) không bị đổi thành số 5
    s = re.sub(r"\bnăm\s+(\d{4})\b", r" @y\1 ", s)
    s = re.sub(rf"\bnăm\s+{NEXT}\b", " @ynext ", s)
    s = re.sub(r"\bnăm\s+nay\b", " @ythis ", s)
    s = re.sub(r"\b(cuối|đầu|giữa|trong|hết)\s+năm\b", r"\1 @year", s)
    s = re.sub(r"\btháng\s+(giêng|chạp)\b", lambda m: f"tháng {MONTH_WORDS[m.group(1)]}", s)
    s = _words_to_digits(re.sub(r"\s+", " ", s).strip())
    return re.sub(r"\s+", " ", s).strip()


# ---------- Bước 2: các phép tính ngày ----------


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + (d.month - 1) + n, 12)
    return date(y, m + 1, 1)


def _last_day(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _absolute(s: str, base: date) -> DueResult | None:
    """25/11, 25-11-2026, ngày 25 tháng 11 (năm 2026), ngày 25, mùng 5 tháng sau."""
    m = re.search(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{2,4}))?\b", s) or re.search(
        r"\b(?:ngày|mùng|mồng)?\s*(\d{1,2})\s*tháng\s*(\d{1,2})\b(?:\s*@y(\d{4}))?", s
    )
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
        if year is not None and year < 100:
            year += 2000
        if year is None and "@ynext" in s:
            year = base.year + 1
        if year is not None:
            d = _safe_date(year, month, day)
            return DueResult(d, False, "ngày tháng năm") if d else None
        d = _safe_date(base.year, month, day)
        if d is None:
            return None
        if d < base:
            # Lùi xa hơn nửa năm (họp 28/12, nói "ngày 5 tháng 1") → hiểu là năm sau.
            # Lùi gần (họp 16/11, nói "10/11") → giữ nguyên và đánh dấu để người dùng kiểm tra
            # (có thể nghe sai số, hoặc đang nhắc một ngày đã qua).
            if (base - d).days > 180:
                return DueResult(_safe_date(base.year + 1, month, day), True, "ngày tháng (sang năm sau)")
            return DueResult(d, True, "ngày tháng (đã qua)")
        return DueResult(d, False, "ngày tháng")

    m = re.search(rf"\b(?:ngày|mùng|mồng)\s*(\d{{1,2}})\b(?:\s*tháng\s*({NEXT}|này))?", s)
    if m:
        day, which = int(m.group(1)), m.group(2)
        month_start = base.replace(day=1)
        if which and which != "này":
            month_start = _add_months(base, 1)
        elif not which and day < base.day:  # "ngày 5" nói hôm 16 → ngày 5 tháng sau
            month_start = _add_months(base, 1)
        d = _safe_date(month_start.year, month_start.month, day)
        return DueResult(d, False, "ngày trong tháng") if d else None
    return None


def _weekday(s: str, base: date) -> DueResult | None:
    """thứ Sáu tuần này / tuần sau / (không nói tuần nào)."""
    m = re.search(r"@wd(\d)", s)
    if not m:
        return None
    wd = int(m.group(1))
    if re.search(rf"tuần\s+{NEXT}\s+nữa", s):
        return DueResult(_monday(base) + timedelta(days=14 + wd), False, "thứ, tuần sau nữa")
    if re.search(rf"tuần\s+{NEXT}", s):
        return DueResult(_monday(base) + timedelta(days=7 + wd), False, "thứ, tuần sau")
    if re.search(r"tuần\s+này", s):
        d = _monday(base) + timedelta(days=wd)
        return DueResult(d, d < base, "thứ, tuần này")
    # Không nói tuần nào → lần gần nhất SAU ngày họp (họp thứ Sáu, nói "thứ Sáu nộp" = thứ Sáu tuần sau)
    ahead = (wd - base.weekday()) % 7 or 7
    return DueResult(base + timedelta(days=ahead), False, "thứ gần nhất")


def _relative(s: str, base: date) -> DueResult | None:
    """hôm nay, ngày mai, ngày kia, 3 ngày nữa, 2 tuần nữa."""
    if "@plus2" in s:
        return DueResult(base + timedelta(days=2), False, "ngày kia")
    if re.search(r"\b(?:ngày\s+)?mai\b", s):
        return DueResult(base + timedelta(days=1), False, "ngày mai")
    if re.search(r"\b(?:hôm|bữa)\s+nay\b|\btrong\s+ngày\b|\bcuối\s+(?:ngày|giờ|buổi)\b|\btối\s+nay\b|\bchiều\s+nay\b", s):
        return DueResult(base, False, "hôm nay")
    m = re.search(r"\b(\d{1,3})\s*(?:ngày|hôm)\s*(?:nữa|tới|sau)\b|\b(?:trong|sau)\s+(\d{1,3})\s*(?:ngày|hôm)\b", s)
    if m:
        return DueResult(base + timedelta(days=int(m.group(1) or m.group(2))), False, "N ngày nữa")
    m = re.search(r"\b(\d{1,2})\s*tuần\s*(?:nữa|tới|sau)\b|\b(?:trong|sau)\s+(\d{1,2})\s*tuần\b", s)
    if m:
        return DueResult(base + timedelta(weeks=int(m.group(1) or m.group(2))), False, "N tuần nữa")
    if re.search(r"\btuần\s+nữa\b", s):
        return DueResult(base + timedelta(weeks=1), False, "1 tuần nữa")
    m = re.search(r"\b(\d{1,2})\s*tháng\s*(?:nữa|tới)\b", s)
    if m:
        n = int(m.group(1))
        start = _add_months(base, n)
        d = _safe_date(start.year, start.month, base.day) or _last_day(start)
        return DueResult(d, True, "N tháng nữa")
    return None


def _vague(s: str, base: date) -> DueResult | None:
    """Cách nói mơ hồ → ƯỚC LƯỢNG theo quy ước đã chốt (approximate = True):
    cuối tuần = Chủ nhật, đầu tuần = thứ Hai, giữa tuần = thứ Tư, cuối tháng = ngày cuối tháng.
    """
    mon = _monday(base)
    nxt = bool(re.search(rf"(?:tuần|tháng)\s+{NEXT}", s))

    if re.search(r"\bcuối\s+tuần\b", s):
        return DueResult(mon + timedelta(days=13 if nxt else 6), True, "cuối tuần = Chủ nhật")
    if re.search(r"\bđầu\s+tuần\b", s):
        if re.search(r"tuần\s+này", s):
            return DueResult(mon, True, "đầu tuần này = thứ Hai")
        return DueResult(mon + timedelta(days=7), True, "đầu tuần = thứ Hai tuần sau")
    if re.search(r"\bgiữa\s+tuần\b", s):
        return DueResult(mon + timedelta(days=9 if nxt else 2), True, "giữa tuần = thứ Tư")

    m = re.search(r"\b(đầu|giữa|cuối|hết)\s+tháng\s+(\d{1,2})\b", s)
    if m and 1 <= int(m.group(2)) <= 12:
        month = int(m.group(2))
        first = date(base.year + (1 if month < base.month else 0), month, 1)
        d = {"đầu": first, "giữa": first.replace(day=15)}.get(m.group(1), _last_day(first))
        return DueResult(d, True, f"{m.group(1)} tháng N")
    if re.search(r"\bcuối\s+tháng\b", s):
        return DueResult(_last_day(_add_months(base, 1) if nxt else base), True, "cuối tháng = ngày cuối tháng")
    if re.search(r"\bđầu\s+tháng\b", s):
        return DueResult(_add_months(base, 1), True, "đầu tháng = ngày 1 tháng sau")
    if re.search(r"\bgiữa\s+tháng\b", s):
        start = _add_months(base, 1) if nxt or base.day > 15 else base.replace(day=1)
        return DueResult(start.replace(day=15), True, "giữa tháng = ngày 15")
    if re.search(r"\b(?:cuối|hết)\s+(?:@year|@ythis|@ynext)", s):
        return DueResult(date(base.year + (1 if "@ynext" in s else 0), 12, 31), True, "cuối năm = 31/12")

    # "trong tuần sau" / "tuần này" không nói thứ mấy → hết tuần đó (Chủ nhật)
    if re.search(rf"\btuần\s+{NEXT}\b", s):
        return DueResult(mon + timedelta(days=13), True, "tuần sau = Chủ nhật tuần sau")
    if re.search(r"\btuần\s+này\b", s):
        return DueResult(mon + timedelta(days=6), True, "tuần này = Chủ nhật tuần này")
    if re.search(rf"\btháng\s+{NEXT}\b", s):
        return DueResult(_last_day(_add_months(base, 1)), True, "tháng sau = cuối tháng sau")
    if re.search(r"\btháng\s+này\b", s):
        return DueResult(_last_day(base), True, "tháng này = cuối tháng này")
    return None


def _fallback(text: str, base: date) -> DueResult | None:
    """Lưới đỡ cuối: thư viện dateparser. Chỉ thử khi có chữ số, để câu như "càng sớm càng tốt"
    không bị đoán bừa thành một ngày nào đó."""
    if not re.search(r"\d", text):
        return None
    try:
        import dateparser

        dt = dateparser.parse(
            text,
            languages=["vi"],
            settings={
                "RELATIVE_BASE": datetime(base.year, base.month, base.day),
                "PREFER_DATES_FROM": "future",
                "DATE_ORDER": "DMY",
            },
        )
    except Exception:  # noqa: BLE001 — thư viện ngoài, lỗi gì cũng coi như không hiểu
        return None
    return DueResult(dt.date(), True, "dateparser") if dt else None


def parse_due(text: str | None, base: date) -> DueResult:
    """Đổi `text` thành ngày, lấy `base` (ngày họp) làm mốc. Không hiểu → date = None."""
    if not text or not text.strip():
        return DueResult(None)
    s = normalize(text)
    for rule in (_absolute, _weekday, _relative, _vague):
        r = rule(s, base)
        if r and r.date:
            return r
    return _fallback(text, base) or DueResult(None)
