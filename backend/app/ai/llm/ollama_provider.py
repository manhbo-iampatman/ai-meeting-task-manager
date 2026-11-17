"""LLM chạy ngay trên máy qua Ollama (mặc định Qwen2.5 3B) — dùng để SO SÁNH với Gemini
ở chương thực nghiệm, và để hệ thống chạy được hoàn toàn offline (không gửi nội dung
cuộc họp ra ngoài).

Ollama là một chương trình chạy nền, mở API HTTP ở cổng 11434. Tham số `format` nhận
JSON schema → mô hình bị ép sinh đúng cấu trúc (giống structured output của Gemini).

Cài đặt (làm 1 lần):  tải Ollama tại https://ollama.com  rồi chạy  `ollama pull qwen2.5:3b`
"""

from typing import Any

import httpx

from app.ai.llm.base import LLMError, parse_json_text


class OllamaProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        num_ctx: int = 8192,
        keep_alive: str = "30s",
        temperature: float = 0.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.temperature = temperature
        self.name = f"ollama/{model}"
        self.last_usage: dict[str, int] | None = None
        # Mô hình nhỏ chỉ đọc được `num_ctx` token mỗi lần (mặc định 8192). Tiếng Việt khoảng
        # 3 ký tự/token; chừa một nửa cho prompt hệ thống + câu trả lời → mỗi đoạn tối đa
        # ~1,5 ký tự × num_ctx. Bản ghi dài hơn thì bị chia đoạn (map-reduce).
        self.max_input_chars = int(num_ctx * 1.5)
        # Mô hình chạy bằng CPU/GPU của máy nên chậm → cho chờ tới 10 phút mỗi lần gọi
        self._http = httpx.Client(timeout=httpx.Timeout(600.0, connect=5.0), transport=transport)

    def generate_json(self, system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": schema,  # ép JSON đúng schema
            "stream": False,
            # keep_alive: giữ mô hình trong VRAM bao lâu sau khi trả lời. Để ngắn vì GPU 4GB
            # còn phải nhường chỗ cho Whisper ở cuộc họp tiếp theo.
            "keep_alive": self.keep_alive,
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx},
        }
        try:
            r = self._http.post(f"{self.base_url}/api/chat", json=body)
        except httpx.ConnectError as e:
            raise LLMError(
                f"Không kết nối được Ollama tại {self.base_url}. Hãy cài Ollama, mở nó lên, "
                f"rồi chạy: ollama pull {self.model}"
            ) from e
        except httpx.TimeoutException as e:
            raise LLMError("Ollama xử lý quá lâu (hơn 10 phút). Thử mô hình nhỏ hơn hoặc bản ghi ngắn hơn.") from e
        except httpx.HTTPError as e:
            raise LLMError(f"Lỗi khi gọi Ollama: {type(e).__name__}") from e

        if r.status_code == 404:
            raise LLMError(f"Ollama chưa có mô hình “{self.model}”. Hãy chạy: ollama pull {self.model}")
        if r.status_code >= 400:
            raise LLMError(f"Ollama báo lỗi {r.status_code}: {r.text[:200]}")

        data = r.json()
        self.last_usage = {
            "input_tokens": data.get("prompt_eval_count") or 0,
            "output_tokens": data.get("eval_count") or 0,
        }
        return parse_json_text((data.get("message") or {}).get("content"))
