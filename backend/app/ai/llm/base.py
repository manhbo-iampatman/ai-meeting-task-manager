"""Giao diện chung cho LLM (Gemini, Ollama, ...). Cài đặt cụ thể ở Giai đoạn 4."""

from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str

    def generate_json(self, system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Gọi LLM và ép kết quả trả về đúng JSON schema (structured output)."""
        ...
