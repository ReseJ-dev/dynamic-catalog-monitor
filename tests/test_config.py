"""Tests for application settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def test_settings_read_environment_file(tmp_path: Path) -> None:
    """Settings parse environment values into their declared types."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "CATALOG_URL=https://shop.example.test/catalog",
                "HEADLESS=false",
                "MAX_LOAD_MORE_CLICKS=7",
                "PAGE_TIMEOUT_MS=15000",
                "OUTPUT_DIR=generated-reports",
                "DATABASE_URL=sqlite+aiosqlite:///data/test.db",
                "SAVE_FAILURE_SCREENSHOTS=false",
                "LOG_LEVEL=DEBUG",
                "DIAGNOSTICS_DIR=debug-artifacts",
                "MAX_ITEMS=125",
                "SCRAPER_PROFILE=scraping_sandbox",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert str(settings.catalog_url) == "https://shop.example.test/catalog"
    assert settings.headless is False
    assert settings.max_load_more_clicks == 7
    assert settings.page_timeout_ms == 15_000
    assert settings.output_dir == Path("generated-reports")
    assert settings.diagnostics_dir == Path("debug-artifacts")
    assert settings.max_items == 125
    assert settings.scraper_profile == "scraping_sandbox"


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("max_load_more_clicks", 0),
        ("max_load_more_clicks", -1),
        ("page_timeout_ms", 0),
        ("max_items", 0),
    ],
)
def test_settings_reject_non_positive_limits(field_name: str, invalid_value: int) -> None:
    """Iteration limits and timeouts must be positive."""

    with pytest.raises(ValidationError):
        Settings.model_validate({field_name: invalid_value})


def test_settings_reject_invalid_catalog_url() -> None:
    """The catalog address must be a valid HTTP or HTTPS URL."""

    with pytest.raises(ValidationError):
        Settings(catalog_url="not-a-url")


def test_get_settings_returns_cached_instance() -> None:
    """Repeated settings access returns the same process-wide instance."""

    get_settings.cache_clear()

    assert get_settings() is get_settings()
