from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ai_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    cors_origins: str = "http://localhost:3000"
    max_upload_size_mb: int = 10
    ai_structure_max_retries: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
