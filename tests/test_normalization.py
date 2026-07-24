"""Tests for standalone product normalization functions."""

from decimal import Decimal

import pytest

from app.services.normalization import (
    NormalizationError,
    normalize_availability,
    normalize_currency,
    normalize_price,
    normalize_rating,
    normalize_text,
    normalize_url,
)


@pytest.mark.parametrize(
    ("raw_price", "expected"),
    [
        ("$1,299.99", Decimal("1299.99")),
        ("€ 1.299,99", Decimal("1299.99")),
        ("£1,299", Decimal("1299")),
        ("19,95", Decimal("19.95")),
    ],
)
def test_normalize_price_supports_common_formats(
    raw_price: str,
    expected: Decimal,
) -> None:
    """US and European thousands and decimal separators are supported."""

    assert normalize_price(raw_price) == expected


@pytest.mark.parametrize("raw_price", ["", "free", "$--"])
def test_normalize_price_rejects_invalid_values(raw_price: str) -> None:
    """Invalid prices raise a domain-specific error instead of becoming zero."""

    with pytest.raises(NormalizationError, match="price"):
        normalize_price(raw_price)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (" In Stock ", "in_stock"),
        ("OUT OF STOCK", "out_of_stock"),
        ("Limited availability", "limited"),
        ("Pre-order", "pre_order"),
    ],
)
def test_normalize_availability(raw_value: str, expected: str) -> None:
    """Availability labels are mapped to stable values."""

    assert normalize_availability(raw_value) == expected


def test_normalize_rating_extracts_numeric_value() -> None:
    """Ratings embedded in descriptive text are extracted."""

    assert normalize_rating("4.6 out of 5") == 4.6
    assert normalize_rating(None) is None


def test_normalize_rating_rejects_non_numeric_value() -> None:
    """A nonempty rating without a number cannot be normalized."""

    with pytest.raises(NormalizationError, match="rating"):
        normalize_rating("not rated")


@pytest.mark.parametrize(
    ("raw_currency", "raw_price", "expected"),
    [
        ("usd", None, "USD"),
        ("€", None, "EUR"),
        (None, "£ 25.00", "GBP"),
        (None, "$25.00", "USD"),
    ],
)
def test_normalize_currency_supports_codes_and_symbols(
    raw_currency: str | None,
    raw_price: str | None,
    expected: str,
) -> None:
    """Currency codes are normalized and supported symbols are inferred."""

    assert normalize_currency(raw_currency, raw_price) == expected


def test_normalize_url_resolves_relative_path() -> None:
    """Relative product paths are resolved against the catalog URL."""

    assert (
        normalize_url("/products/fixture-001", "https://example.test/catalog")
        == "https://example.test/products/fixture-001"
    )


def test_normalize_text_collapses_whitespace() -> None:
    """Text normalization trims and collapses repeated whitespace."""

    assert normalize_text("  Fixture \n Product  ") == "Fixture Product"
    assert normalize_text("  ") is None
