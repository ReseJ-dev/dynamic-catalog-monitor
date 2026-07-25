"""Integration tests for async repositories against a temporary SQLite database."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.database import create_database_engine, create_session_factory, initialize_database
from app.db.repositories import CatalogRepository
from app.models import Product

SCRAPED_AT = datetime(2026, 7, 25, 9, 30, tzinfo=UTC)


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[CatalogRepository]:
    """Provide an initialized repository backed by a test-only SQLite file."""

    database_path = tmp_path / "catalog.db"
    engine: AsyncEngine = create_database_engine(f"sqlite+aiosqlite:///{database_path}")
    await initialize_database(engine)
    try:
        yield CatalogRepository(create_session_factory(engine))
    finally:
        await engine.dispose()


def make_product(**overrides: object) -> Product:
    """Build a validated product for repository tests."""

    values: dict[str, object] = {
        "product_id": "sku-001",
        "title": "Fixture Product",
        "category": "Fixtures",
        "price": Decimal("19.99"),
        "currency": "USD",
        "availability": "in_stock",
        "rating": 4.5,
        "description": "Fixture description",
        "image_url": "https://example.test/images/fixture.jpg",
        "product_url": "https://example.test/products/fixture",
        "scraped_at": SCRAPED_AT,
    }
    values.update(overrides)
    return Product.model_validate(values)


async def test_save_and_load_completed_run_products(repository: CatalogRepository) -> None:
    """Completed run snapshots round-trip as application products with Decimal prices."""

    run = await repository.create_scrape_run(started_at=SCRAPED_AT)
    product = make_product(price=Decimal("19.95"))

    snapshots = await repository.save_products_for_run(run.id, [product])
    completed = await repository.mark_run_completed(
        run.id,
        products_found=1,
        products_valid=1,
        products_invalid=0,
        finished_at=SCRAPED_AT + timedelta(minutes=1),
    )
    loaded_products = await repository.load_products_for_run(run.id)
    latest_run = await repository.load_latest_completed_run()

    assert len(snapshots) == 1
    assert snapshots[0].price == Decimal("19.95")
    assert completed.status == "completed"
    assert latest_run is not None
    assert latest_run.id == run.id
    assert loaded_products == [product]


async def test_upsert_updates_product_and_last_seen_timestamp(
    repository: CatalogRepository,
) -> None:
    """Upserting the same external ID updates descriptive fields rather than duplicating it."""

    first = await repository.upsert_product(make_product())
    later_time = SCRAPED_AT + timedelta(hours=1)
    updated = await repository.upsert_product(
        make_product(title="Updated Fixture", category=None, scraped_at=later_time)
    )

    assert updated.id == first.id
    assert updated.title == "Updated Fixture"
    assert updated.category is None
    assert updated.last_seen_at == later_time

    manually_updated = await repository.update_last_seen_at(
        first.id,
        SCRAPED_AT + timedelta(hours=2),
    )

    assert manually_updated.last_seen_at == SCRAPED_AT + timedelta(hours=2)


async def test_two_latest_completed_snapshots_return_previous_then_current(
    repository: CatalogRepository,
) -> None:
    """Only the two latest completed runs are returned in comparison order."""

    first_run = await repository.create_scrape_run(started_at=SCRAPED_AT)
    await repository.save_products_for_run(first_run.id, [make_product(price=Decimal("10.00"))])
    await repository.mark_run_completed(
        first_run.id,
        products_found=1,
        products_valid=1,
        products_invalid=0,
        finished_at=SCRAPED_AT + timedelta(minutes=1),
    )

    second_run = await repository.create_scrape_run(started_at=SCRAPED_AT + timedelta(days=1))
    await repository.save_products_for_run(second_run.id, [make_product(price=Decimal("12.00"))])
    await repository.mark_run_completed(
        second_run.id,
        products_found=1,
        products_valid=1,
        products_invalid=0,
        finished_at=SCRAPED_AT + timedelta(days=1, minutes=1),
    )

    snapshots = await repository.load_two_latest_completed_snapshots()

    assert snapshots is not None
    previous, current = snapshots
    assert previous[0].price == Decimal("10.00")
    assert current[0].price == Decimal("12.00")


async def test_failed_run_retains_snapshots_saved_before_failure(
    repository: CatalogRepository,
) -> None:
    """A failed run keeps already persisted valid data for diagnostics and recovery."""

    run = await repository.create_scrape_run(started_at=SCRAPED_AT)
    product = make_product()
    await repository.save_products_for_run(run.id, [product])
    failed = await repository.mark_run_failed(
        run.id,
        error_message="detail page failed",
        products_found=2,
        products_valid=1,
        products_invalid=1,
        finished_at=SCRAPED_AT + timedelta(minutes=1),
    )

    saved_products = await repository.load_products_for_run(run.id)

    assert failed.status == "failed"
    assert failed.error_message == "detail page failed"
    assert saved_products == [product]
    assert await repository.load_latest_completed_run() is None
