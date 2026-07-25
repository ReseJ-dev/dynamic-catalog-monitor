"""Command-line interface for the Dynamic Product Catalog Monitor."""

import asyncio

import typer

from app.config import get_settings
from app.db.database import create_database_engine, create_session_factory, initialize_database
from app.db.repositories import CatalogRepository
from app.services.orchestration import CatalogRunResult, CatalogRunService
from app.utils.logging import configure_logging

app = typer.Typer(
    name="dynamic-catalog-monitor",
    help="Monitor a dynamic product catalog and report changes.",
    no_args_is_help=True,
)


@app.command()
def scrape() -> None:
    """Collect, validate, persist, compare, and report the current catalog."""

    result = asyncio.run(_run_scrape())
    if result.status != "completed":
        typer.echo(f"Scrape run {result.run_id} failed.", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Scrape run {result.run_id} completed: {result.report_path}")


@app.command()
def compare() -> None:
    """Compare collected catalog snapshots."""
    typer.echo("Comparison is not implemented yet.")


@app.command()
def export() -> None:
    """Export catalog results."""
    typer.echo("Export is not implemented yet.")


async def _run_scrape() -> CatalogRunResult:
    """Initialize infrastructure and execute the complete asynchronous scrape workflow."""

    settings = get_settings()
    logger = configure_logging(settings.log_level)
    engine = create_database_engine(settings.database_url)
    await initialize_database(engine)
    try:
        repository = CatalogRepository(create_session_factory(engine))
        return await CatalogRunService(settings, repository, logger).run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    app()
