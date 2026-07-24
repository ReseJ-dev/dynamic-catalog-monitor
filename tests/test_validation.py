"""Tests for application-level model validation."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import Product, RawProduct
from app.services.validation import (
    ProductValidationError,
    validate_products,
    validate_raw_product,
)

SCRAPED_AT = datetime(2026, 7, 24, 9, 30, tzinfo=UTC)
BASE_URL = "https://example.test/catalog"


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
        "scraped_at": SCRAPED_AT,
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
        scraped_at=SCRAPED_AT,
    )

    assert raw_product.product_id == "  sku-001  "
    assert raw_product.price == "$19.99"


def make_raw_product(**overrides: object) -> RawProduct:
    """Build a complete raw scraper record with optional overrides."""

    values: dict[str, object] = {
        "product_id": " fixture-001 ",
        "title": " Fixture Product ",
        "category": " Fixtures ",
        "price": "$1,299.99",
        "currency": None,
        "availability": " In Stock ",
        "rating": "4.6 out of 5",
        "description": " Offline fixture. ",
        "image_url": "/images/fixture-001.jpg",
        "product_url": "/products/fixture-001",
    }
    values.update(overrides)
    return RawProduct.model_validate(values)


def test_validate_raw_product_creates_normalized_product() -> None:
    """A complete raw record becomes a typed, normalized product."""

    product = validate_raw_product(
        make_raw_product(),
        base_url=BASE_URL,
        scraped_at=SCRAPED_AT,
    )

    assert product.product_id == "fixture-001"
    assert product.title == "Fixture Product"
    assert product.price == Decimal("1299.99")
    assert product.currency == "USD"
    assert product.availability == "in_stock"
    assert product.rating == 4.6
    assert str(product.product_url) == "https://example.test/products/fixture-001"
    assert str(product.image_url) == "https://example.test/images/fixture-001.jpg"
    assert product.scraped_at == SCRAPED_AT


@pytest.mark.parametrize(
    ("field_name", "missing_value"),
    [
        ("product_id", "  "),
        ("title", None),
        ("product_url", None),
    ],
)
def test_validate_raw_product_reports_missing_required_field(
    field_name: str,
    missing_value: object,
) -> None:
    """Missing identity and URL fields are reported by their field names."""

    with pytest.raises(ProductValidationError) as error_info:
        validate_raw_product(
            make_raw_product(**{field_name: missing_value}),
            base_url=BASE_URL,
            scraped_at=SCRAPED_AT,
        )

    assert any(detail["field"] == field_name for detail in error_info.value.details)
    assert field_name in str(error_info.value)


def test_validate_raw_product_reports_out_of_range_rating() -> None:
    """The Product model enforces the rating domain after extraction."""

    with pytest.raises(ProductValidationError) as error_info:
        validate_raw_product(
            make_raw_product(rating="5.5 out of 5"),
            base_url=BASE_URL,
            scraped_at=SCRAPED_AT,
        )

    assert error_info.value.details[0]["field"] == "rating"


def test_validate_products_separates_and_preserves_invalid_records() -> None:
    """Batch validation keeps good products and the original bad records."""

    valid_raw = make_raw_product()
    invalid_raw = make_raw_product(title=None, price="not a price")

    products, invalid_records = validate_products(
        [valid_raw, invalid_raw],
        base_url=BASE_URL,
        scraped_at=SCRAPED_AT,
    )

    assert len(products) == 1
    assert products[0].product_id == "fixture-001"
    assert len(invalid_records) == 1
    assert invalid_records[0].raw_product == invalid_raw
    assert "title" in invalid_records[0].reason
    assert {detail["field"] for detail in invalid_records[0].errors} == {
        "currency",
        "price",
        "title",
    }
