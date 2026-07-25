"""Transactional repositories for catalog products and scrape snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import SessionFactory, session_context
from app.db.models import ProductRecord, ProductSnapshot, ScrapeRun
from app.models import Product


class CatalogRepository:
    """Persist and retrieve catalog data through independent transactions."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_scrape_run(self, *, started_at: datetime | None = None) -> ScrapeRun:
        """Create a running scrape record and return it."""

        run = ScrapeRun(
            started_at=started_at or _utc_now(),
            status="running",
            products_found=0,
            products_valid=0,
            products_invalid=0,
        )
        async with session_context(self._session_factory) as session:
            session.add(run)
            await session.flush()
        return run

    async def mark_run_completed(
        self,
        run_id: int,
        *,
        products_found: int,
        products_valid: int,
        products_invalid: int,
        finished_at: datetime | None = None,
    ) -> ScrapeRun:
        """Mark a run completed after its valid products have been stored."""

        async with session_context(self._session_factory) as session:
            run = await _require_run(session, run_id)
            run.status = "completed"
            run.finished_at = finished_at or _utc_now()
            run.products_found = products_found
            run.products_valid = products_valid
            run.products_invalid = products_invalid
            run.error_message = None
            await session.flush()
        return run

    async def mark_run_failed(
        self,
        run_id: int,
        *,
        error_message: str,
        products_found: int,
        products_valid: int,
        products_invalid: int,
        finished_at: datetime | None = None,
    ) -> ScrapeRun:
        """Mark a run failed without deleting snapshots saved earlier in the run."""

        async with session_context(self._session_factory) as session:
            run = await _require_run(session, run_id)
            run.status = "failed"
            run.finished_at = finished_at or _utc_now()
            run.products_found = products_found
            run.products_valid = products_valid
            run.products_invalid = products_invalid
            run.error_message = error_message
            await session.flush()
        return run

    async def upsert_product(self, product: Product) -> ProductRecord:
        """Insert or update the durable identity fields for one product."""

        async with session_context(self._session_factory) as session:
            record = await _find_product_record(session, product)
            if record is None:
                record = ProductRecord(
                    external_id=product.product_id,
                    title=product.title,
                    category=product.category,
                    product_url=str(product.product_url),
                    normalized_product_url=_normalized_url(str(product.product_url)),
                    image_url=str(product.image_url) if product.image_url is not None else None,
                    created_at=product.scraped_at,
                    last_seen_at=product.scraped_at,
                )
                session.add(record)
            else:
                _update_product_record(record, product)
            await session.flush()
        return record

    async def save_snapshot(
        self,
        run_id: int,
        product_id: int,
        product: Product,
    ) -> ProductSnapshot:
        """Save or update a product's snapshot for one scrape run."""

        async with session_context(self._session_factory) as session:
            snapshot = await session.scalar(
                select(ProductSnapshot).where(
                    ProductSnapshot.run_id == run_id,
                    ProductSnapshot.product_id == product_id,
                )
            )
            if snapshot is None:
                snapshot = ProductSnapshot(
                    run_id=run_id,
                    product_id=product_id,
                    price=product.price,
                    currency=product.currency,
                    availability=product.availability,
                    rating=product.rating,
                    description=product.description,
                    scraped_at=product.scraped_at,
                )
                session.add(snapshot)
            else:
                _update_snapshot(snapshot, product)
            await session.flush()
        return snapshot

    async def save_products_for_run(
        self,
        run_id: int,
        products: list[Product],
    ) -> list[ProductSnapshot]:
        """Atomically upsert a batch of valid products and save their snapshots."""

        snapshots: list[ProductSnapshot] = []
        async with session_context(self._session_factory) as session:
            await _require_run(session, run_id)
            for product in products:
                record = await _find_product_record(session, product)
                if record is None:
                    record = ProductRecord(
                        external_id=product.product_id,
                        title=product.title,
                        category=product.category,
                        product_url=str(product.product_url),
                        normalized_product_url=_normalized_url(str(product.product_url)),
                        image_url=str(product.image_url) if product.image_url is not None else None,
                        created_at=product.scraped_at,
                        last_seen_at=product.scraped_at,
                    )
                    session.add(record)
                    await session.flush()
                else:
                    _update_product_record(record, product)

                snapshot = await _upsert_snapshot(session, run_id, record.id, product)
                snapshots.append(snapshot)
            await session.flush()
        return snapshots

    async def update_last_seen_at(self, product_id: int, seen_at: datetime) -> ProductRecord:
        """Set the last observed timestamp for a persisted product."""

        async with session_context(self._session_factory) as session:
            record = await session.get(ProductRecord, product_id)
            if record is None:
                raise LookupError(f"product {product_id} does not exist")
            record.last_seen_at = seen_at
            await session.flush()
        return record

    async def load_latest_completed_run(self) -> ScrapeRun | None:
        """Load the most recently finished successful run, if one exists."""

        async with self._session_factory() as session:
            return cast(ScrapeRun | None, await session.scalar(_completed_runs_query().limit(1)))

    async def load_products_for_run(self, run_id: int) -> list[Product]:
        """Load a run's snapshots as application-level products."""

        async with self._session_factory() as session:
            rows = await session.execute(
                select(ProductSnapshot, ProductRecord)
                .join(ProductRecord, ProductSnapshot.product_id == ProductRecord.id)
                .where(ProductSnapshot.run_id == run_id)
                .order_by(ProductSnapshot.id)
            )
            return [_product_from_row(snapshot, record) for snapshot, record in rows.all()]

    async def load_two_latest_completed_snapshots(
        self,
    ) -> tuple[list[Product], list[Product]] | None:
        """Load the previous and current product snapshots from successful runs."""

        async with self._session_factory() as session:
            runs = (await session.scalars(_completed_runs_query().limit(2))).all()
            if len(runs) < 2:
                return None
            current_run, previous_run = runs
            previous_products = await _load_products_for_run(session, previous_run.id)
            current_products = await _load_products_for_run(session, current_run.id)
            return previous_products, current_products


async def _require_run(session: AsyncSession, run_id: int) -> ScrapeRun:
    """Return a run or raise an explicit lookup error."""

    run = await session.get(ScrapeRun, run_id)
    if run is None:
        raise LookupError(f"scrape run {run_id} does not exist")
    return run


async def _find_product_record(session: AsyncSession, product: Product) -> ProductRecord | None:
    """Find a durable product by external ID first and normalized URL second."""

    by_external_id = cast(
        ProductRecord | None,
        await session.scalar(
            select(ProductRecord).where(ProductRecord.external_id == product.product_id)
        ),
    )
    if by_external_id is not None:
        return by_external_id
    return cast(
        ProductRecord | None,
        await session.scalar(
            select(ProductRecord).where(
                ProductRecord.normalized_product_url == _normalized_url(str(product.product_url))
            )
        ),
    )


def _update_product_record(record: ProductRecord, product: Product) -> None:
    """Update a durable product's descriptive fields from a newer observation."""

    record.external_id = product.product_id
    record.title = product.title
    record.category = product.category
    record.product_url = str(product.product_url)
    record.normalized_product_url = _normalized_url(str(product.product_url))
    record.image_url = str(product.image_url) if product.image_url is not None else None
    record.last_seen_at = product.scraped_at


async def _upsert_snapshot(
    session: AsyncSession,
    run_id: int,
    product_id: int,
    product: Product,
) -> ProductSnapshot:
    """Create or update a product snapshot within an existing transaction."""

    snapshot = await session.scalar(
        select(ProductSnapshot).where(
            ProductSnapshot.run_id == run_id,
            ProductSnapshot.product_id == product_id,
        )
    )
    if snapshot is None:
        snapshot = ProductSnapshot(
            run_id=run_id,
            product_id=product_id,
            price=product.price,
            currency=product.currency,
            availability=product.availability,
            rating=product.rating,
            description=product.description,
            scraped_at=product.scraped_at,
        )
        session.add(snapshot)
    else:
        _update_snapshot(snapshot, product)
    return snapshot


def _update_snapshot(snapshot: ProductSnapshot, product: Product) -> None:
    """Overwrite dynamic snapshot fields with a newer product observation."""

    snapshot.price = product.price
    snapshot.currency = product.currency
    snapshot.availability = product.availability
    snapshot.rating = product.rating
    snapshot.description = product.description
    snapshot.scraped_at = product.scraped_at


def _completed_runs_query() -> Select[tuple[ScrapeRun]]:
    """Return the canonical ordering for successful catalog runs."""

    return (
        select(ScrapeRun)
        .where(ScrapeRun.status == "completed")
        .order_by(ScrapeRun.finished_at.desc(), ScrapeRun.id.desc())
    )


async def _load_products_for_run(session: AsyncSession, run_id: int) -> list[Product]:
    """Load a run's product models using a caller-owned session."""

    rows = await session.execute(
        select(ProductSnapshot, ProductRecord)
        .join(ProductRecord, ProductSnapshot.product_id == ProductRecord.id)
        .where(ProductSnapshot.run_id == run_id)
        .order_by(ProductSnapshot.id)
    )
    return [_product_from_row(snapshot, record) for snapshot, record in rows.all()]


def _product_from_row(snapshot: ProductSnapshot, record: ProductRecord) -> Product:
    """Convert joined persistence rows into a validated application product."""

    return Product(
        product_id=record.external_id or str(record.id),
        title=record.title,
        category=record.category,
        price=snapshot.price,
        currency=snapshot.currency,
        availability=snapshot.availability,
        rating=snapshot.rating,
        description=snapshot.description,
        image_url=record.image_url,
        product_url=record.product_url,
        scraped_at=_as_utc(snapshot.scraped_at),
    )


def _normalized_url(value: str) -> str:
    """Normalize URL host casing and trailing slash for storage uniqueness."""

    parsed = urlsplit(value)
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, ""))


def _as_utc(value: datetime) -> datetime:
    """Restore UTC awareness when SQLite returns a naive datetime."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)
