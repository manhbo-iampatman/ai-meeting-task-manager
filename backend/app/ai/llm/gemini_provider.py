"""LLM chính: Gemini API của Google (gói miễn phí).

Dùng "structured output": gửi kèm JSON schema, API bảo đảm câu trả lời là JSON đúng
cấu trúc đó → không phải tự bóc JSON ra khỏi một đoạn văn tự do.

Mô hình dự phòng (GEMINI_FALLBACK_MODEL)
----------------------------------------
Gói miễn phí hay bị quá tải: ngày 17/11/2026 `gemini-3.5-flash` lúc trả 503 sau ~20 giây,
lúc chờ 300 giây vẫn ra 504, trong khi `gemini-3.5-flash-lite` trả lời trong ~3 giây. Nên:

    gọi mô hình chính ──ok──► xong
          │
          └─ 429 (hết hạn mức) / 503 (quá tải) / 504 hoặc hết thời gian chờ
                 ──► chuyển NGAY sang mô hình dự phòng (không thử lại mô hình chính)

Đã chuyển thì dùng mô hình dự phòng cho hết các lần gọi còn lại của CÙNG một lần tóm tắt
(bản ghi dài bị chia nhiều đoạn), để không phải chờ thêm cho mỗi đoạn và cả biên bản do
một mô hình viết. Lần tóm tắt sau (`begin_job`) lại thử mô hình chính trước.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

from app.ai.llm.base import LLMError, parse_json_text

log = logging.getLogger(__name__)

# Mã lỗi tạm thời → đáng thử lại: 429 (quá hạn mức / quá nhanh), 500 / 503 (máy chủ Google bận)
RETRYABLE = {429, 500, 503}
# Mã lỗi khiến mô hình chính bị bỏ qua, chuyển sang mô hình dự phòng (nếu có cấu hình)
SWITCH_TO_FALLBACK = {429, 503, 504}

_REASONS = {
    429: "đã hết hạn mức miễn phí (429)",
    503: "đang quá tải (503)",
    504: "phản hồi quá chậm (504)",
    "timeout": "phản hồi quá chậm (hết thời gian chờ)",
}


class _SwitchToFallback(Exception):
    def __init__(self, reason: int | str):
        super().__init__(str(reason))
        self.reason = reason


def _is_timeout(e: BaseException) -> bool:
    """Thư viện google-genai có thể dùng httpx hoặc httpx2 → nhận diện lỗi hết giờ theo tên lớp."""
    seen = 0
    cur: BaseException | None = e
    while cur is not None and seen < 5:
        if isinstance(cur, TimeoutError) or "Timeout" in type(cur).__name__:
            return True
        cur, seen = cur.__cause__ or cur.__context__, seen + 1
    return False


class GeminiProvider:
    # Gemini Flash đọc được khoảng 1 triệu token. 200.000 ký tự ≈ 3–4 giờ họp → hầu như
    # không bao giờ phải chia đoạn; giới hạn này chỉ để phòng bản ghi quá lớn.
    max_input_chars = 200_000

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.2,
        timeout_sec: int = 60,
        client: Any = None,
        retry_wait: float = 2.0,
        fallback_model: str = "",
    ):
        if client is None:
            if not api_key:
                raise LLMError("Chưa cấu hình GEMINI_API_KEY trong file backend/.env")
            from google import genai
            from google.genai import types

            # HttpOptions.timeout tính bằng mili giây. Thư viện gửi kèm giá trị này cho máy chủ
            # (header X-Server-Timeout) → quá thời gian thì chính Google trả lỗi 504.
            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_sec * 1000))
        self._client = client
        self.model = model
        self.fallback_model = fallback_model if fallback_model and fallback_model != model else ""
        self.temperature = temperature
        self.retry_wait = retry_wait
        self.last_usage: dict[str, int] | None = None  # số token của lần gọi gần nhất (để báo cáo chi phí)
        self.begin_job()

    @property
    def name(self) -> str:
        """Mô hình THỰC SỰ đang dùng, vd. "gemini/gemini-3.5-flash-lite" nếu đã chuyển sang dự phòng."""
        return f"gemini/{self._active}"

    def begin_job(self, on_fallback: Callable[[str], None] | None = None) -> None:
        """Gọi ở đầu mỗi lần tóm tắt: quay lại mô hình chính.

        `on_fallback(thông báo)` được gọi đúng lúc chuyển sang mô hình dự phòng → worker
        hiện thông báo đó trên giao diện.
        """
        self._active = self.model
        self.fallback_from: str | None = None  # mô hình chính đã bị bỏ qua (None = không phải chuyển)
        self._on_fallback = on_fallback

    def generate_json(self, system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_json_schema=schema,
            # Nhiệt độ thấp: cùng một bản ghi cho kết quả gần như giống nhau giữa các lần chạy
            temperature=self.temperature,
        )
        can_switch = bool(self.fallback_model) and self._active == self.model
        try:
            resp = self._generate(self._active, user_prompt, config, can_switch)
        except _SwitchToFallback as e:
            reason = _REASONS.get(e.reason, str(e.reason))
            log.warning("Gemini %s %s → chuyển sang mô hình dự phòng %s", self.model, reason, self.fallback_model)
            self._active, self.fallback_from = self.fallback_model, self.model
            if self._on_fallback:
                self._on_fallback(
                    f"Mô hình {self.model} {reason}, hệ thống đã tự chuyển sang mô hình dự phòng {self.fallback_model}…"
                )
            try:
                resp = self._generate(self._active, user_prompt, config, can_switch=False)
            except LLMError as e2:
                raise LLMError(f"Mô hình chính {self.model} {reason}; mô hình dự phòng cũng lỗi: {e2}") from e2

        usage = getattr(resp, "usage_metadata", None)
        if usage is not None:
            self.last_usage = {
                "input_tokens": getattr(usage, "prompt_token_count", None) or 0,
                "output_tokens": getattr(usage, "candidates_token_count", None) or 0,
            }
        return parse_json_text(resp.text)

    def _generate(self, model: str, user_prompt: str, config: Any, can_switch: bool) -> Any:
        """Gọi 1 mô hình, tự thử lại lỗi tạm thời. `can_switch=True` → gặp lỗi quá tải thì
        ném `_SwitchToFallback` ngay thay vì thử lại (thử lại mô hình đang quá tải chỉ tốn thời gian)."""
        from google.genai import errors

        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                return self._client.models.generate_content(model=model, contents=user_prompt, config=config)
            except errors.APIError as e:
                code = getattr(e, "code", None)
                if can_switch and code in SWITCH_TO_FALLBACK:
                    raise _SwitchToFallback(code) from e
                if code in RETRYABLE and attempt < attempts:
                    wait = self.retry_wait * 2 ** (attempt - 1)  # 2 giây, 4 giây (exponential backoff)
                    log.warning("Gemini %s lỗi %s — thử lại sau %.0f giây (lần %d/%d)", model, code, wait, attempt, attempts)
                    time.sleep(wait)
                    continue
                raise LLMError(_friendly_error(code, str(getattr(e, "message", "") or e), model)) from e
            except Exception as e:  # noqa: BLE001 — mất mạng, hết thời gian chờ...
                if can_switch and _is_timeout(e):
                    raise _SwitchToFallback("timeout") from e
                if attempt < attempts:
                    time.sleep(self.retry_wait * 2 ** (attempt - 1))
                    continue
                if _is_timeout(e):
                    raise LLMError(
                        f"Mô hình {model} phản hồi quá chậm nên bị ngắt. Thử lại sau ít phút, hoặc đổi "
                        "GEMINI_MODEL / GEMINI_FALLBACK_MODEL trong backend/.env rồi khởi động lại worker."
                    ) from e
                raise LLMError(f"Không kết nối được Gemini API ({type(e).__name__}). Kiểm tra kết nối Internet.") from e
        raise AssertionError("unreachable")


def _friendly_error(code: int | None, message: str, model: str = "") -> str:
    which = f" {model}" if model else ""
    if code == 429:
        return (
            f"Gemini API báo mô hình{which} hết hạn mức miễn phí hoặc gọi quá nhanh (429). "
            "Chờ vài phút rồi thử lại, hoặc đổi LLM_PROVIDER=ollama."
        )
    if code in (401, 403) or "API key" in message:
        return "GEMINI_API_KEY không hợp lệ hoặc không có quyền dùng mô hình này. Kiểm tra lại file backend/.env."
    if code == 404:
        return (
            f"Không tìm thấy mô hình Gemini{which}. Kiểm tra lại GEMINI_MODEL / GEMINI_FALLBACK_MODEL "
            "trong backend/.env."
        )
    if code in (500, 503):
        return f"Máy chủ Gemini đang quá tải (mô hình{which}). Hãy thử lại sau ít phút."
    if code == 504:
        return (
            f"Mô hình{which} phản hồi quá chậm nên bị ngắt (504) — đang quá tải. Thử lại sau ít phút, "
            "hoặc đổi GEMINI_MODEL / GEMINI_FALLBACK_MODEL trong backend/.env rồi khởi động lại worker."
        )
    return f"Gemini API báo lỗi {code or ''}: {message[:200]}".strip()
