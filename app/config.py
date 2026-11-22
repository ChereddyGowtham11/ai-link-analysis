from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-6-luna"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    llm_timeout_seconds: float = Field(60, gt=0, le=120)
    http_timeout_seconds: float = Field(15, gt=0, le=30)
    max_website_chars: int = Field(16_000, ge=4096, le=32_000)
    max_crawl_pages: int = Field(4, ge=1, le=4)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
