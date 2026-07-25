"""Tests for the complete catalog-run coordinator using fake infrastructure."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from playwright.async_api import Page

from app.config import Settings
from app.db.models import ScrapeRun
from app.models import Product, RawProduct
from app.services.orchestration import CatalogRunService


@dataclass
class FakeRun:
    """Small stand-in for a persisted scrape run."""

    id: int


class FakePage:
    """Diagnostic-capable page fake; no browser process is created."""

    url = "https://example.test/catalog"

    async def screenshot(self, *, path: str) -> None:
        """Write a fake screenshot artifact."""

        Path(path).write_bytes(b"fake-image")

    async def content(self) -> str:
        """Return fake HTML for diagnostics."""

        return "<html>fake page</html>"


class FakeBrowser:
    """Async browser context manager that exposes a fake page."""

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._page = FakePage()
        self.closed = False

    @property
    def page(self) -> Page:
        """Return the fake page as a Playwright page type for the coordinator."""

        return cast(Page, self._page)

    async def __aenter__(self) -> FakeBrowser:
        """Record browser startup."""

        self._events.append("browser_enter")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Record browser cleanup."""

        del exc_type, exc_value, traceback
        self.closed = True
        self._events.append("browser_exit")


class FakeScraper:
    """A scraper fake that returns prebuilt raw records."""

    def __init__(self, products: list[RawProduct]) -> None:
        self._products = products

    async def collect_products(self) -> list[RawProduct]:
        """Return raw records without navigation or a live website."""

        return self._products


class FakeRepository:
    """Repository fake that records orchestration calls and persisted data."""

    def __init__(self, events: list[str], previous_products: list[Product] | None = None) -> None:
        self._events = events
        self._previous_products = previous_products or []
        self.saved_products: list[Product] = []
        self.completed_arguments: dict[str, int] | None = None
        self.failed_arguments: dict[str, object] | None = None

    async def create_scrape_run(self, *, started_at: datetime | None = None) -> ScrapeRun:
        """Record creation before browser startup."""

        assert started_at is not None
        self._events.append("create_run")
        return cast(ScrapeRun, FakeRun(id=17))

    async def save_products_for_run(self, run_id: int, products: list[Product]) -> object:
        """Record products persisted for the active run."""

        assert run_id == 17
        self._events.append("save_products")
        self.saved_products = products
        return object()

    async def load_latest_completed_run(self) -> ScrapeRun | None:
        """Return a successful baseline only when configured."""

        self._events.append("load_previous_run")
        return cast(ScrapeRun, FakeRun(id=16)) if self._previous_products else None

    async def load_products_for_run(self, run_id: int) -> list[Product]:
        """Return the configured baseline snapshot."""

        assert run_id == 16
        return self._previous_products

    async def mark_run_completed(
        self,
        run_id: int,
        *,
        products_found: int,
        products_valid: int,
        products_invalid: int,
        finished_at: datetime | None = None,
    ) -> object:
        """Record completion counters."""

        assert run_id == 17
        assert finished_at is not None
        self._events.append("mark_completed")
        self.completed_arguments = {
            "products_found": products_found,
            "products_valid": products_valid,
            "products_invalid": products_invalid,
        }
        return object()

    async def mark_run_failed(
        self,
        run_id: int,
        *,
        error_message: str,
        products_found: int,
        products_valid: int,
        products_invalid: int,
        finished_at: datetime | None = None,
    ) -> object:
        """Record failure counters and error context."""

        assert run_id == 17
        assert finished_at is not None
        self._events.append("mark_failed")
        self.failed_arguments = {
            "error_message": error_message,
            "products_found": products_found,
            "products_valid": products_valid,
            "products_invalid": products_invalid,
        }
        return object()


def raw_product(**overrides: object) -> RawProduct:
    """Build a raw record that validates to a complete product."""

    values: dict[str, object] = {
        "product_id": "sku-001",
        "title": "Fixture Product",
        "price": "$19.99",
        "currency": "USD",
        "availability": "In Stock",
        "rating": "4.5 out of 5",
        "product_url": "https://example.test/products/fixture",
    }
    values.update(overrides)
    return RawProduct.model_validate(values)


def domain_product(**overrides: object) -> Product:
    """Build a validated baseline product for comparison tests."""

    values: dict[str, object] = {
        "product_id": "sku-001",
        "title": "Fixture Product",
        "price": Decimal("10.00"),
        "currency": "USD",
        "availability": "in_stock",
        "product_url": "https://example.test/products/fixture",
        "scraped_at": datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return Product.model_validate(values)


def make_service(
    tmp_path: Path,
    repository: FakeRepository,
    products: list[RawProduct],
    events: list[str],
    *,
    report_generator: Callable[..., Path],
) -> CatalogRunService:
    """Build a coordinator with fake browser, scraper, and report dependencies."""

    settings = Settings(
        catalog_url="https://example.test/catalog",
        output_dir=tmp_path / "reports",
        diagnostics_dir=tmp_path / "diagnostics",
    )
    browser = FakeBrowser(events)

    def browser_factory() -> FakeBrowser:
        """Return the fake browser context manager."""

        return browser

    def scraper_factory(page: Page, _settings: Settings, _logger: logging.Logger) -> FakeScraper:
        """Return a raw-record scraper without using the page."""

        assert page is browser.page
        return FakeScraper(products)

    return CatalogRunService(
        settings,
        repository,
        logging.getLogger("test.orchestration"),
        browser_factory=browser_factory,
        scraper_factory=scraper_factory,
        report_generator=report_generator,
    )


async def test_orchestration_completes_first_run_and_persists_unique_valid_products(
    tmp_path: Path,
) -> None:
    """The first success creates a run first and treats every unique product as new."""

    events: list[str] = []
    repository = FakeRepository(events)
    report_path = tmp_path / "reports" / "report.xlsx"

    def report_generator(*args: object, **kwargs: object) -> Path:
        """Return a deterministic report path without exercising Excel in this unit test."""

        del args, kwargs
        return report_path

    service = make_service(
        tmp_path,
        repository,
        [raw_product(), raw_product(), raw_product(product_id=None)],
        events,
        report_generator=report_generator,
    )

    result = await service.run()

    assert result.status == "completed"
    assert result.run_id == 17
    assert result.comparison_summary.new_products == 1
    assert result.comparison_summary.removed_products == 0
    assert result.counters.total_scraped == 3
    assert result.counters.valid_products == 2
    assert result.counters.invalid_records == 1
    assert result.counters.duplicates_removed == 1
    assert repository.completed_arguments == {
        "products_found": 3,
        "products_valid": 2,
        "products_invalid": 1,
    }
    assert len(repository.saved_products) == 1
    assert (
        events.index("create_run") < events.index("browser_enter") < events.index("save_products")
    )
    assert events[-1] == "browser_exit"


async def test_orchestration_compares_completed_baseline_and_keeps_data_on_report_failure(
    tmp_path: Path,
) -> None:
    """A later failure keeps snapshots, writes diagnostics, and marks the run failed."""

    events: list[str] = []
    repository = FakeRepository(events, previous_products=[domain_product()])

    def failing_report_generator(*args: object, **kwargs: object) -> Path:
        """Fail after persistence to exercise the recovery path."""

        del args, kwargs
        raise RuntimeError("report generation failed")

    service = make_service(
        tmp_path,
        repository,
        [raw_product()],
        events,
        report_generator=failing_report_generator,
    )

    result = await service.run()

    assert result.status == "failed"
    assert repository.saved_products[0].price == Decimal("19.99")
    assert repository.failed_arguments is not None
    assert repository.failed_arguments["products_valid"] == 1
    assert "report generation failed" in str(repository.failed_arguments["error_message"])
    assert result.diagnostic_artifacts is not None
    assert result.diagnostic_artifacts.metadata_path is not None
    assert result.diagnostic_artifacts.metadata_path.exists()
    assert "mark_failed" in events
    assert events[-1] == "browser_exit"


async def test_orchestration_compares_against_the_latest_completed_snapshot(tmp_path: Path) -> None:
    """A completed baseline supplies price changes to a later successful run."""

    events: list[str] = []
    repository = FakeRepository(events, previous_products=[domain_product()])
    report_path = tmp_path / "reports" / "report.xlsx"

    def report_generator(*args: object, **kwargs: object) -> Path:
        """Return a report path while preserving the comparison-focused test scope."""

        del args, kwargs
        return report_path

    service = make_service(
        tmp_path,
        repository,
        [raw_product()],
        events,
        report_generator=report_generator,
    )

    result = await service.run()

    assert result.status == "completed"
    assert result.comparison_summary.new_products == 0
    assert result.comparison_summary.price_changes == 1
    assert result.comparison.price_changes[0].old_price == Decimal("10.00")
    assert result.comparison.price_changes[0].new_price == Decimal("19.99")
