from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["dev", "prod"] = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    output_dir: Path = Path("generated")
    use_mock_mode: bool = True

    # Accept multiple keys for simple failover/rotation.
    seedance_api_keys: str = Field(default="")
    seedance_base_url: str = Field(default="https://modelark.byteplus.com")
    seedance_model: str = Field(default="seedance-2.0")

    seedream_api_key: str = Field(default="")
    seedream_base_url: str = Field(default="https://modelark.byteplus.com")
    seedream_model: str = Field(default="seedream-5.0-lite")

    seed_speech_api_key: str = Field(default="")
    seed_speech_base_url: str = Field(default="https://openspeech.bytedance.com")
    seed_speech_voice: str = Field(default="en_female_1")

    openai_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    # Optional: powers /api/chat when set (used before OpenAI/Anthropic for chat).
    gemini_api_key: str = Field(default="")
    gemini_chat_model: str = Field(default="gemini-2.0-flash")
    script_provider: Literal["openai", "anthropic"] = "openai"
    script_model: str = Field(default="gpt-4o-mini")

    request_timeout_s: int = 60
    poll_interval_s: int = 6
    poll_timeout_s: int = 240
    min_unique_story_frames: int = 4

    # Optional scrape fallback that can bypass anti-bot pages.
    use_firecrawl: bool = False
    firecrawl_api_key: str = Field(default="")
    firecrawl_base_url: str = Field(default="https://api.firecrawl.dev/v1")

    # Property chat: refresh listing URL + optional web search each turn.
    chat_web_research: bool = True
    chat_research_total_timeout_s: int = 28
    chat_listing_excerpt_chars: int = 7000
    chat_research_max_chars: int = 14_000
    chat_search_max_results: int = 4
    chat_search_snippet_chars: int = 360

    def seedance_key_pool(self) -> list[str]:
        return [k.strip() for k in self.seedance_api_keys.split(",") if k.strip()]

    def seedream_key_pool(self) -> list[str]:
        return [k.strip() for k in self.seedream_api_key.split(",") if k.strip()]

    def seed_speech_key_pool(self) -> list[str]:
        return [k.strip() for k in self.seed_speech_api_key.split(",") if k.strip()]

    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
