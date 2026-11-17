"""Chọn LLM theo cấu hình (biến môi trường LLM_PROVIDER = gemini | ollama)."""

from app.ai.llm.base import LLMError, LLMProvider
from app.core.config import get_settings

__all__ = ["LLMError", "LLMProvider", "get_llm_provider"]

_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        s = get_settings()
        if s.LLM_PROVIDER == "gemini":
            from app.ai.llm.gemini_provider import GeminiProvider

            _provider = GeminiProvider(
                api_key=s.GEMINI_API_KEY,
                model=s.GEMINI_MODEL,
                fallback_model=s.GEMINI_FALLBACK_MODEL,
                temperature=s.LLM_TEMPERATURE,
                timeout_sec=s.LLM_TIMEOUT_SEC,
            )
        else:
            from app.ai.llm.ollama_provider import OllamaProvider

            _provider = OllamaProvider(
                base_url=s.OLLAMA_URL,
                model=s.OLLAMA_MODEL,
                num_ctx=s.OLLAMA_NUM_CTX,
                keep_alive=s.OLLAMA_KEEP_ALIVE,
                temperature=s.LLM_TEMPERATURE,
            )
    return _provider
