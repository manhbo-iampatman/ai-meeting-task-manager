"""Giao diện chung cho LLM (Gemini, Ollama, ...).

Giống STTProvider ở Giai đoạn 3 (mẫu thiết kế Strategy): phần còn lại của hệ thống chỉ
biết tới `LLMProvider`. Đổi mô hình = đổi biến môi trường LLM_PROVIDER, không sửa code.
Chương thực nghiệm so sánh Gemini với Qwen cũng dùng đúng cơ chế này.
"""

import json
import re
from typing import Any, Protocol


class LLMError(Exception):
    """Lỗi gọi LLM, kèm thông báo tiếng Việt đủ rõ để hiện thẳng cho người dùng."""


class LLMProvider(Protocol):
    name: str  # vd. "gemini/gemini-3.5-flash" — lưu lại để biết biên bản do mô hình nào sinh ra
    # Bản ghi dài hơn ngần này ký tự thì phải chia đoạn (mỗi mô hình đọc được một lượng chữ khác nhau)
    max_input_chars: int

    def generate_json(self, system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Gọi LLM và ép kết quả trả về đúng JSON schema (structured output)."""
        ...

    # Không bắt buộc (provider nào có mô hình dự phòng thì cài, vd. GeminiProvider):
    #   begin_job(on_fallback)  — gọi ở đầu mỗi lần tóm tắt; on_fallback(thông báo) chạy lúc chuyển mô hình
    #   fallback_from           — tên mô hình chính đã bị bỏ qua, None nếu không phải chuyển


def parse_json_text(text: str | None) -> dict[str, Any]:
    """Đọc JSON do LLM trả về. Mô hình nhỏ đôi khi bọc trong ```json ... ``` → gỡ ra trước."""
    if not text or not text.strip():
        raise LLMError("Mô hình AI trả về kết quả rỗng")
    s = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.DOTALL)
    if fenced:
        s = fenced.group(1)
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise LLMError(f"Mô hình AI trả về JSON không hợp lệ ({e.msg})") from e
    if not isinstance(data, dict):
        raise LLMError("Mô hình AI trả về sai định dạng (không phải object JSON)")
    return data
