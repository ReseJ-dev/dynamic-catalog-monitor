"""Application service that coordinates one complete catalog collection run."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from playwright.async_api import Page

from app.config import Settings
from app.db.models import ScrapeRun
from app.models import ComparisonResult, Product, RawProduct, RunSummary
from app.scraper.browser import BrowserManager
from app.scraper.catalog import CatalogScraper
from app.scraper.selectors import CatalogSelectors, DetailPageSelectors
from app.services.comparison import compare_snapshots
from app.services.deduplication import deduplicate_products
from app.services.reporting import generate_catalog_report
from app.services.validation import validate_products
from app.utils.diagnostics import DiagnosticArtifacts, save_failure_diagnostics


class BrowserSession(Protocol):
    """The browser context-manager interface required by the coordinator."""

    @property
    def page(self) -> Page:
        """Return the active browser page."""

    async def __aenter__(self) -> BrowserSession:
        """Start browser resources and return the active session."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Close browser resources."""


class CatalogCollector(Protocol):
    """The collection operation used by the orchestration layer."""

    async def collect_products(self) -> list[RawProduct]:
        """Load and collect raw catalog products."""


class RunRepository(Protocol):
    """The persistence operations required for one scrape run."""

    async def create_scrape_run(self, *, started_at: datetime | None = None) -> ScrapeRun:
        """Create the database record for a running scrape."""

    async def mark_run_completed(
        self,
        run_id: int,
        *,
        products_found: int,
        products_valid: int,
        products_invalid: int,
        finished_at: datetime | None = None,
    ) -> object:
        """Mark a persisted scrape run as completed."""

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
        """Mark a persisted scrape run as failed."""

    async def save_products_for_run(self, run_id: int, products: list[Product]) -> object:
        """Persist unique valid products and their snapshots for a run."""

    async def load_latest_completed_run(self) -> ScrapeRun | None:
        """Load the baseline run without including failed runs."""

    async def load_products_for_run(self, run_id: int) -> list[Product]:
        """Load one run's product snapshots as domain products."""


BrowserFactory = Callable[[], BrowserSession]
ScraperFactory = Callable[[Page, Settings, logging.Logger], CatalogCollector]
ReportGenerator = Callable[..., Path]


@dataclass(frozen=True)
class ComparisonSummary:
    """Counts that describe a completed snapshot comparison."""

    new_products: int
    removed_products: int
    price_changes: int
    availability_changes: int
    unchanged_products: int


@dataclass(frozen=True)
class CatalogRunResult:
    """Structured outcome of a completed or failed catalog run."""

    run_id: int | None
    status: str
    counters: RunSummary
    report_path: Path | None
    comparison: ComparisonResult
    comparison_summary: ComparisonSummary
    diagnostic_artifacts: DiagnosticArtifacts | None = None


class CatalogRunService:
    """Coordinate collection, validation, persistence, comparison, and reporting."""

    def __init__(
        self,
        settings: Settings,
        repository: RunRepository,
        logger: logging.Logger,
        *,
        browser_factory: BrowserFactory | None = None,
        scraper_factory: ScraperFactory | None = None,
        report_generator: ReportGenerator = generate_catalog_report,
    ) -> None:
        """Store infrastructure dependencies for one or more catalog runs."""

        self._settings = settings
        self._repository = repository
        self._logger = logger
        self._browser_factory = browser_factory or self._default_browser_factory
        self._scraper_factory = scraper_factory or self._default_scraper_factory
        self._report_generator = report_generator

    async def run(self) -> CatalogRunResult:
        """Execute one complete catalog run and return a structured outcome."""

        started_at = datetime.now(UTC)
        stage = "create_scrape_run"
        raw_products: list[RawProduct] = []
        valid_products: list[Product] = []
        invalid_count = 0
        duplicate_count = 0
        run: ScrapeRun | None = None
        page: Page | None = None

        try:
            self._logger.info("Starting catalog collection")
            run = await self._repository.create_scrape_run(started_at=started_at)
            stage = "open_browser"
            async with self._browser_factory() as browser:
                page = browser.page
                try:
                    stage = "collect_products"
                    scraper = self._scraper_factory(page, self._settings, self._logger)
                    raw_products = await scraper.collect_products()
                    self._logger.info("Collected %d product cards", len(raw_products))

                    stage = "validate_products"
                    valid_products, invalid_records = validate_products(
                        raw_products,
                        base_url=str(self._settings.catalog_url),
                        scraped_at=started_at,
                    )
                    invalid_count = len(invalid_records)
                    self._logger.info(
                        "Valid products: %d; invalid products: %d",
                        len(valid_products),
                        invalid_count,
                    )

                    stage = "deduplicate_products"
                    unique_products, duplicates = deduplicate_products(valid_products)
                    duplicate_count = len(duplicates)
                    if duplicate_count:
                        self._logger.info("Rejected duplicate products: %d", duplicate_count)

                    stage = "persist_products"
                    await self._repository.save_products_for_run(run.id, unique_products)

                    stage = "load_previous_snapshot"
                    previous_run = await self._repository.load_latest_completed_run()
                    previous_products = (
                        await self._repository.load_products_for_run(previous_run.id)
                        if previous_run is not None
                        else []
                    )

                    stage = "compare_snapshots"
                    comparison = _comparison_for_run(previous_products, unique_products)
                    comparison_summary = _comparison_summary(comparison)
                    self._logger.info(
                        "Price changes detected: %d; availability changes detected: %d",
                        comparison_summary.price_changes,
                        comparison_summary.availability_changes,
                    )

                    counters = RunSummary(
                        total_scraped=len(raw_products),
                        valid_products=len(valid_products),
                        invalid_records=invalid_count,
                        duplicates_removed=duplicate_count,
                        added_products=comparison_summary.new_products,
                        removed_products=comparison_summary.removed_products,
                        changed_products=len(
                            {
                                *(
                                    change.product_id
                                    for change in comparison.price_changes
                                ),
                                *(
                                    change.product_id
                                    for change in comparison.availability_changes
                                ),
                            }
                        ),
                    )

                    stage = "generate_report"
                    finished_at = datetime.now(UTC)
                    report_path = self._report_generator(
                        unique_products,
                        comparison,
                        invalid_records,
                        counters,
                        reports_dir=self._settings.output_dir,
                        started_at=started_at,
                        finished_at=finished_at,
                        status="completed",
                    )
                    self._logger.info("Report created successfully: %s", report_path)

                    stage = "mark_run_completed"
                    await self._repository.mark_run_completed(
                        run.id,
                        products_found=len(raw_products),
                        products_valid=len(valid_products),
                        products_invalid=invalid_count,
                        finished_at=finished_at,
                    )
                    self._logger.info(
                        "Run summary: collected=%d valid=%d invalid=%d duplicates=%d",
                        counters.total_scraped,
                        counters.valid_products,
                        counters.invalid_records,
                        counters.duplicates_removed,
                    )
                    self._logger.info("Catalog collection completed: run %d", run.id)
                    return CatalogRunResult(
                        run_id=run.id,
                        status="completed",
                        counters=counters,
                        report_path=report_path,
                        comparison=comparison,
                        comparison_summary=comparison_summary,
                    )
                except Exception as error:
                    return await self._failed_result(
                        run,
                        error,
                        stage=stage,
                        page=page,
                        raw_products=raw_products,
                        valid_products=valid_products,
                        invalid_count=invalid_count,
                        duplicate_count=duplicate_count,
                    )
        except Exception as error:
            return await self._failed_result(
                run,
                error,
                stage=stage,
                page=page,
                raw_products=raw_products,
                valid_products=valid_products,
                invalid_count=invalid_count,
                duplicate_count=duplicate_count,
            )

    async def _failed_result(
        self,
        run: ScrapeRun | None,
        error: Exception,
        *,
        stage: str,
        page: Page | None,
        raw_products: list[RawProduct],
        valid_products: list[Product],
        invalid_count: int,
        duplicate_count: int,
    ) -> CatalogRunResult:
        """Save diagnostics, mark the run failed, and return a non-raising failure result."""

        self._logger.exception("Catalog collection failed during %s", stage)
        artifacts = await save_failure_diagnostics(
            page,
            error,
            diagnostics_dir=self._settings.diagnostics_dir,
            stage=stage,
            products_collected=len(raw_products),
            run_id=run.id if run is not None else None,
            save_screenshot=self._settings.save_failure_screenshots,
        )
        counters = RunSummary(
            total_scraped=len(raw_products),
            valid_products=len(valid_products),
            invalid_records=invalid_count,
            duplicates_removed=duplicate_count,
        )
        if run is not None:
            try:
                await self._repository.mark_run_failed(
                    run.id,
                    error_message=str(error),
                    products_found=len(raw_products),
                    products_valid=len(valid_products),
                    products_invalid=invalid_count,
                    finished_at=datetime.now(UTC),
                )
            except Exception:
                self._logger.exception("Unable to mark scrape run %d as failed", run.id)
        return CatalogRunResult(
            run_id=run.id if run is not None else None,
            status="failed",
            counters=counters,
            report_path=None,
            comparison=ComparisonResult(),
            comparison_summary=_comparison_summary(ComparisonResult()),
            diagnostic_artifacts=artifacts,
        )

    def _default_browser_factory(self) -> BrowserManager:
        """Create the standard configured Playwright browser manager."""

        return BrowserManager(
            headless=self._settings.headless,
            timeout_ms=self._settings.page_timeout_ms,
        )

    @staticmethod
    def _default_scraper_factory(
        page: Page,
        settings: Settings,
        logger: logging.Logger,
    ) -> CatalogScraper:
        """Create the standard dynamic catalog scraper."""

        return CatalogScraper(
            page,
            CatalogSelectors(),
            DetailPageSelectors(),
            settings,
            logger,
        )


def _comparison_for_run(
    previous_products: list[Product],
    current_products: list[Product],
) -> ComparisonResult:
    """Treat the first successful run as entirely new without removed or changed products."""

    if not previous_products:
        return ComparisonResult(new_products=list(current_products))
    return compare_snapshots(previous_products, current_products)


def _comparison_summary(comparison: ComparisonResult) -> ComparisonSummary:
    """Build stable comparison counts for logs, reports, and result consumers."""

    return ComparisonSummary(
        new_products=len(comparison.new_products),
        removed_products=len(comparison.removed_products),
        price_changes=len(comparison.price_changes),
        availability_changes=len(comparison.availability_changes),
        unchanged_products=len(comparison.unchanged_products),
    )
