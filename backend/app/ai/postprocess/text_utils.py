"""Hàm xử lý chuỗi tiếng Việt dùng chung cho bước hậu xử lý."""

import re
import unicodedata


def strip_accents(s: str) -> str:
    """"Nguyễn Văn Đạt" → "Nguyen Van Dat" (bỏ dấu thanh, dấu mũ; đ → d)."""
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    """Chuẩn hóa để so sánh CÓ dấu: chữ thường, dạng NFC, bỏ dấu câu, gộp khoảng trắng."""
    s = unicodedata.normalize("NFC", s).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_no_accent(s: str) -> str:
    """Chuẩn hóa để so sánh KHÔNG dấu."""
    return strip_accents(norm(s))
