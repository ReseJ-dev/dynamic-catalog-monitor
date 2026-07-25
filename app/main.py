"""Production Typer command-line interface for catalog monitoring."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.db.database import create_database_engine, create_session_factory, initialize_database
from app.db.models import ScrapeRun
from app.db.repositories import CatalogRepository
from app.models import ComparisonResult, Product, RunSummary
from app.services.comparison import compare_snapshots
from app.services.orchestration import CatalogRunResult, CatalogRunService
from app.services.reporting import generate_catalog_report
from app.utils.logging import configure_logging

app = typer.Typer(
    name="dynamic-catalog-monitor",
    help="Monitor a dynamic product catalog and report changes.",
    no_args_is_help=True,
)


@dataclass(frozen=True)
class SnapshotCommandResult:
    """Comparison and optional report output for compare and export commands."""

    comparison: ComparisonResult
    report_path: Path | None


@app.command()
def scrape(
    headful: Annotated[
        bool,
        typer.Option("--headful", help="Show the Chromium browser window."),
    ] = False,
    max_items: Annotated[
        int | None,
        typer.Option(
            "--max-items",
            min=1,
            help="Stop after collecting this many product cards.",
        ),
    ] = None,
    catalog_url: Annotated[
        str | None,
        typer.Option(
            "--catalog-url",
            help="Override the configured catalog URL.",
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Directory for generated Excel reports.",
        ),
    ] = None,
) -> None:
    """Scrape, validate, persist, compare, and report the current catalog."""

    settings = _command_settings(
        headful=headful,
        max_items=max_items,
        catalog_url=catalog_url,
        output_dir=output_dir,
    )
    result = asyncio.run(_run_scrape(settings))
    if result.status != "completed":
        typer.echo(f"Scrape run {result.run_id} failed.", err=True)
        raise typer.Exit(code=1)

    _print_scrape_summary(result)


@app.command()
def compare(
    export: Annotated[
        bool,
        typer.Option(
            "--export",
            help="Also generate an Excel report for the comparison.",
        ),
    ] = False,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Directory for an optional generated report.",
        ),
    ] = None,
) -> None:
    """Compare the two most recent completed catalog runs without scraping."""

    settings = _command_settings(output_dir=output_dir)
    result = asyncio.run(_run_compare(settings, export_report=export))
    if result is None:
        typer.echo("At least two completed runs are required for comparison.", err=True)
        raise typer.Exit(code=1)

    _print_comparison_summary(result.comparison)
    if result.report_path is not None:
        typer.echo(f"Report created: {result.report_path}")


@app.command()
def export(
    destination: Annotated[
        Path | None,
        typer.Option(
            "--destination",
            help="Report directory or a new .xlsx file path.",
        ),
    ] = None,
) -> None:
    """Regenerate an Excel report for the latest completed run without scraping."""

    settings = _command_settings()
    result = asyncio.run(_run_export(settings, destination=destination))
    if result is None:
        typer.echo("No completed run is available to export.", err=True)
        raise typer.Exit(code=1)

    _print_comparison_summary(result.comparison)
    if result.report_path is not None:
        typer.echo(f"Report created: {result.report_path}")


def _command_settings(
    *,
    headful: bool = False,
    max_items: int | None = None,
    catalog_url: str | None = None,
    output_dir: Path | None = None,
) -> Settings:
    """Apply command-line overrides while preserving Pydantic settings validation."""

    values = get_settings().model_dump(mode="python")
    if headful:
        values["headless"] = False
    if max_items is not None:
        values["max_items"] = max_items
    if catalog_url is not None:
        values["catalog_url"] = catalog_url
    if output_dir is not None:
        values["output_dir"] = output_dir
    try:
        return Settings.model_validate(values)
    except ValidationError as error:
        typer.echo(f"Invalid command option: {error}", err=True)
        raise typer.Exit(code=2) from error


async def _run_scrape(settings: Settings) -> CatalogRunResult:
    """Initialize infrastructure and execute the complete asynchronous scrape workflow."""

    logger = configure_logging(settings.log_level)
    engine = create_database_engine(settings.database_url)
    await initialize_database(engine)
    try:
        repository = CatalogRepository(create_session_factory(engine))
        return await CatalogRunService(settings, repository, logger).run()
    finally:
        await engine.dispose()


async def _run_compare(
    settings: Settings,
    *,
    export_report: bool,
) -> SnapshotCommandResult | None:
    """Load two completed snapshots, compare them, and optionally export a report."""

    logger = configure_logging(settings.log_level)
    engine = create_database_engine(settings.database_url)
    await initialize_database(engine)
    try:
        repository = CatalogRepository(create_session_factory(engine))
        snapshots = await repository.load_two_latest_completed_snapshots()
        latest_run = await repository.load_latest_completed_run()
        if snapshots is None or latest_run is None:
            return None
        previous_products, current_products = snapshots
        comparison = compare_snapshots(previous_products, current_products)
        report_path = (
            _export_report(settings, latest_run, current_products, comparison)
            if export_report
            else None
        )
        logger.info("Compared two completed catalog runs")
        return SnapshotCommandResult(comparison=comparison, report_path=report_path)
    finally:
        await engine.dispose()


async def _run_export(
    settings: Settings,
    *,
    destination: Path | None,
) -> SnapshotCommandResult | None:
    """Export the latest completed run and compare it when a baseline is available."""

    logger = configure_logging(settings.log_level)
    engine = create_database_engine(settings.database_url)
    await initialize_database(engine)
    try:
        repository = CatalogRepository(create_session_factory(engine))
        latest_run = await repository.load_latest_completed_run()
        if latest_run is None:
            return None
        current_products = await repository.load_products_for_run(latest_run.id)
        snapshots = await repository.load_two_latest_completed_snapshots()
        comparison = (
            compare_snapshots(*snapshots)
            if snapshots is not None
            else ComparisonResult(new_products=current_products)
        )
        report_path = _export_report(
            settings,
            latest_run,
            current_products,
            comparison,
            destination=destination,
        )
        logger.info("Exported latest completed catalog run %d", latest_run.id)
        return SnapshotCommandResult(comparison=comparison, report_path=report_path)
    finally:
        await engine.dispose()


def _export_report(
    settings: Settings,
    run: ScrapeRun,
    products: list[Product],
    comparison: ComparisonResult,
    *,
    destination: Path | None = None,
) -> Path:
    """Generate a report for one stored run and optionally move it to a requested path."""

    started_at = _run_datetime(run, "started_at")
    finished_at = _run_datetime(run, "finished_at") or datetime.now(UTC)
    reports_dir = (
        destination
        if destination is not None and destination.suffix != ".xlsx"
        else settings.output_dir
    )
    report_path = generate_catalog_report(
        products,
        comparison,
        [],
        RunSummary(
            total_scraped=run.products_found,
            valid_products=run.products_valid,
            invalid_records=run.products_invalid,
            added_products=len(comparison.new_products),
            removed_products=len(comparison.removed_products),
            changed_products=len(
                {
                    *(change.product_id for change in comparison.price_changes),
                    *(change.product_id for change in comparison.availability_changes),
                }
            ),
        ),
        reports_dir=reports_dir,
        started_at=started_at,
        finished_at=finished_at,
        status=run.status,
    )
    if destination is None or destination.suffix != ".xlsx":
        return report_path
    if destination.exists():
        raise typer.BadParameter(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    report_path.rename(destination)
    return destination


def _run_datetime(run: ScrapeRun, attribute: str) -> datetime | None:
    """Read a stored run datetime and restore UTC awareness for report generation."""

    value = run.started_at if attribute == "started_at" else run.finished_at
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _print_scrape_summary(result: CatalogRunResult) -> None:
    """Print concise successful scrape counters and the generated report path."""

    counters = result.counters
    typer.echo(
        "Scrape completed: "
        f"collected={counters.total_scraped}, valid={counters.valid_products}, "
        f"invalid={counters.invalid_records}, duplicates={counters.duplicates_removed}"
    )
    typer.echo(f"Report created: {result.report_path}")


def _print_comparison_summary(comparison: ComparisonResult) -> None:
    """Print concise comparison counts for non-scraping CLI commands."""

    typer.echo(f"New products: {len(comparison.new_products)}")
    typer.echo(f"Removed products: {len(comparison.removed_products)}")
    typer.echo(f"Price changes: {len(comparison.price_changes)}")
    typer.echo(f"Availability changes: {len(comparison.availability_changes)}")
    typer.echo(f"Unchanged products: {len(comparison.unchanged_products)}")


if __name__ == "__main__":
    app()
