"""Tests for snapshot comparison."""

from datetime import UTC, datetime
from decimal import Decimal

from app.models import Product
from app.services.comparison import calculate_change_percent, compare_snapshots

SCRAPED_AT = datetime(2026, 7, 24, 9, 30, tzinfo=UTC)


def make_product(**overrides: object) -> Product:
    """Build a normalized product for comparison tests."""

    values: dict[str, object] = {
        "product_id": "sku-001",
        "title": "Fixture Product",
        "price": Decimal("100.00"),
        "currency": "USD",
        "availability": "in_stock",
        "product_url": "https://example.test/products/fixture-001",
        "scraped_at": SCRAPED_AT,
    }
    values.update(overrides)
    return Product.model_validate(values)


def test_compare_snapshots_finds_new_and_removed_products() -> None:
    """Products exclusive to either snapshot are classified correctly."""

    previous = [make_product(product_id="removed", product_url="https://example.test/removed")]
    current = [make_product(product_id="new", product_url="https://example.test/new")]

    result = compare_snapshots(previous, current)

    assert result.new_products == current
    assert result.removed_products == previous
    assert result.added_products == current


def test_compare_snapshots_reports_price_change() -> None:
    """Price changes include the reporting context and percent difference."""

    result = compare_snapshots([make_product()], [make_product(price=Decimal("125.00"))])

    assert len(result.price_changes) == 1
    change = result.price_changes[0]
    assert change.product_id == "sku-001"
    assert change.product_title == "Fixture Product"
    assert change.old_price == Decimal("100.00")
    assert change.new_price == Decimal("125.00")
    assert change.absolute_difference == Decimal("25.00")
    assert change.percentage_difference == Decimal("25.00")
    assert change.currency == "USD"
    assert str(change.product_url) == "https://example.test/products/fixture-001"


def test_compare_snapshots_reports_availability_change() -> None:
    """Availability changes preserve both statuses and the product URL."""

    result = compare_snapshots(
        [make_product()],
        [make_product(availability="out_of_stock")],
    )

    assert len(result.availability_changes) == 1
    change = result.availability_changes[0]
    assert change.previous_status == "in_stock"
    assert change.current_status == "out_of_stock"
    assert change.product_title == "Fixture Product"


def test_product_with_price_and_availability_changes_is_not_unchanged() -> None:
    """Both change types are reported and the product is excluded from unchanged."""

    result = compare_snapshots(
        [make_product()],
        [make_product(price=Decimal("90.00"), availability="limited")],
    )

    assert len(result.price_changes) == 1
    assert len(result.availability_changes) == 1
    assert result.unchanged_products == []


def test_compare_snapshots_reports_unchanged_products() -> None:
    """Only products with no tracked changes are marked unchanged."""

    product = make_product()

    result = compare_snapshots([product], [product])

    assert result.unchanged_products == [product]


def test_compare_snapshots_uses_url_when_id_is_missing() -> None:
    """A normalized product URL identifies incomplete legacy products."""

    previous = make_product().model_copy(update={"product_id": ""})
    current = make_product(product_url="https://EXAMPLE.test/products/fixture-001/").model_copy(
        update={"product_id": ""}
    )

    result = compare_snapshots([previous], [current])

    assert result.unchanged_products == [current]


def test_calculate_change_percent_handles_increases_decreases_and_zero() -> None:
    """Percentage calculations are signed, rounded, and safe for zero baselines."""

    assert calculate_change_percent(Decimal("100"), Decimal("112.345")) == Decimal("12.35")
    assert calculate_change_percent(Decimal("100"), Decimal("80")) == Decimal("-20.00")
    assert calculate_change_percent(Decimal("0"), Decimal("10")) is None


def test_comparison_module_is_importable() -> None:
    """The comparison layer is available for later implementation."""
    from app.services import comparison

    assert comparison.__doc__
