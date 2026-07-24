"""Tests for application-level model validation."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import Product, RawProduct


def make_product(**overrides: object) -> Product:
    """Build a valid product with optional field overrides."""

    values: dict[str, object] = {
        "product_id": "sku-001",
        "title": "Fixture Product",
        "category": "Fixtures",
        "price": "19.99",
        "currency": "usd",
        "availability": "In stock",
        "rating": 4.5,
        "description": "A fixture product.",
        "image_url": "https://example.test/images/fixture-001.jpg",
        "product_url": "https://example.test/products/fixture-001",
        "scraped_at": datetime(2026, 7, 24, 9, 30, tzinfo=UTC),
    }
    values.update(overrides)
    return Product.model_validate(values)


def test_product_normalizes_text_and_currency() -> None:
    """Validated product text is trimmed and currency is uppercase."""

    product = make_product(
        product_id="  sku-001  ",
        title="  Fixture Product  ",
        category="  Fixtures  ",
        currency=" usd ",
    )

    assert product.product_id == "sku-001"
    assert product.title == "Fixture Product"
    assert product.category == "Fixtures"
    assert product.currency == "USD"
    assert product.price == Decimal("19.99")


@pytest.mark.parametrize("field_name", ["product_id", "title"])
def test_product_rejects_empty_required_text(field_name: str) -> None:
    """Required identifying text cannot be empty after trimming."""

    with pytest.raises(ValidationError):
        make_product(**{field_name: "   "})


def test_product_rejects_negative_price() -> None:
    """A product price cannot be negative."""

    with pytest.raises(ValidationError):
        make_product(price="-0.01")


@pytest.mark.parametrize("rating", [-0.1, 5.1])
def test_product_rejects_rating_outside_range(rating: float) -> None:
    """Ratings must remain within the inclusive zero-to-five range."""

    with pytest.raises(ValidationError):
        make_product(rating=rating)


def test_product_rejects_naive_scraped_timestamp() -> None:
    """Collection timestamps must include timezone information."""

    with pytest.raises(ValidationError, match="timezone-aware"):
        make_product(scraped_at=datetime(2026, 7, 24, 9, 30))


def test_raw_product_preserves_unprocessed_values() -> None:
    """Raw records retain scraper values for later normalization and diagnostics."""

    raw_product = RawProduct(
        product_id="  sku-001  ",
        title="  Fixture Product  ",
        price="$19.99",
        currency="usd",
        scraped_at=datetime(2026, 7, 24, 9, 30, tzinfo=UTC),
    )

    assert raw_product.product_id == "  sku-001  "
    assert raw_product.price == "$19.99"
