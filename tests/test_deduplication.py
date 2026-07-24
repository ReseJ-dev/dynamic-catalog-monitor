"""Tests for deterministic product deduplication."""

from datetime import UTC, datetime
from decimal import Decimal

from app.models import Product
from app.services.deduplication import deduplicate_products, product_identity

SCRAPED_AT = datetime(2026, 7, 24, 9, 30, tzinfo=UTC)


def make_product(**overrides: object) -> Product:
    """Build a valid product with optional test-specific field overrides."""

    values: dict[str, object] = {
        "product_id": "sku-001",
        "title": "Fixture Product",
        "category": None,
        "price": Decimal("19.99"),
        "currency": "USD",
        "availability": "in_stock",
        "rating": None,
        "description": None,
        "image_url": None,
        "product_url": "https://example.test/products/fixture-001",
        "scraped_at": SCRAPED_AT,
    }
    values.update(overrides)
    return Product.model_validate(values)


def test_deduplicate_products_rejects_duplicate_ids() -> None:
    """The product ID is the preferred duplicate identity."""

    first = make_product(title="First title")
    duplicate = make_product(title="Second title", product_url="https://example.test/other")

    unique, duplicates = deduplicate_products([first, duplicate])

    assert unique == [first]
    assert duplicates == [duplicate]


def test_deduplicate_products_uses_url_when_id_is_missing() -> None:
    """A normalized URL is used for legacy products without IDs."""

    first = make_product().model_copy(update={"product_id": ""})
    duplicate = make_product(
        product_id="sku-002",
        title="Different title",
        product_url="https://EXAMPLE.test/products/fixture-001/",
    ).model_copy(update={"product_id": ""})

    unique, duplicates = deduplicate_products([first, duplicate])

    assert unique == [first]
    assert duplicates == [duplicate]


def test_deduplicate_products_uses_title_and_price_as_last_resort() -> None:
    """Title and price are used when a legacy record also lacks a usable URL."""

    first = make_product().model_copy(
        update={"product_id": "", "product_url": "", "title": " Fixture  Product "}
    )
    duplicate = make_product().model_copy(
        update={"product_id": "", "product_url": "", "title": "fixture product"}
    )

    unique, duplicates = deduplicate_products([first, duplicate])

    assert product_identity(first) == product_identity(duplicate)
    assert product_identity(first).startswith("title-price:")
    assert unique == [first]
    assert duplicates == [duplicate]


def test_deduplicate_products_keeps_richer_record() -> None:
    """Optional populated fields determine the winner when identities match."""

    sparse = make_product()
    rich = make_product(category="Fixtures", rating=4.5, description="Details")

    unique, duplicates = deduplicate_products([sparse, rich])

    assert unique == [rich]
    assert duplicates == [sparse]


def test_deduplication_module_is_importable() -> None:
    """The deduplication layer is available for later implementation."""
    from app.services import deduplication

    assert deduplication.__doc__
