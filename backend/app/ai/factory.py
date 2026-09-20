from functools import lru_cache

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.base import AIProvider
from app.config import get_settings


@lru_cache
def get_ai_provider() -> AIProvider:
    settings = get_settings()
    if settings.ai_provider == "anthropic":
        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    raise ValueError(f"Unknown AI_PROVIDER: {settings.ai_provider}")
