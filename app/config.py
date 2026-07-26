"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for catalog collection and persistence."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    catalog_url: HttpUrl = HttpUrl("https://example.test/catalog")
    headless: bool = True
    max_load_more_clicks: PositiveInt = 20
    page_timeout_ms: PositiveInt = 30_000
    output_dir: Path = Path("reports")
    database_url: str = "sqlite+aiosqlite:///data/catalog.db"
    save_failure_screenshots: bool = True
    log_level: str = "INFO"
    diagnostics_dir: Path = Path("diagnostics")
    max_items: PositiveInt | None = Field(default=None)
    scraper_profile: Literal["default", "scraping_sandbox"] = "default"
    demo_scenario: Literal["first", "second"] | None = None


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached application settings."""

    return Settings()
