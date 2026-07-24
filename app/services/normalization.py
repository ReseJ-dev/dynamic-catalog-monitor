"""Small, deterministic product data normalization functions."""

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin


class NormalizationError(ValueError):
    """Raised when a raw value cannot be normalized without guessing."""


def normalize_text(value: str | None) -> str | None:
    """Trim and collapse whitespace, returning ``None`` for blank text."""

    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def normalize_price(raw_price: str) -> Decimal:
    """Convert a price in a common US or European format to a decimal."""

    text = normalize_text(raw_price)
    if text is None:
        raise NormalizationError("price is missing")

    negative_parentheses = text.startswith("(") and text.endswith(")")
    numeric = re.sub(r"[^0-9,.\-+]", "", text)
    if not re.search(r"\d", numeric):
        raise NormalizationError(f"invalid price: {raw_price!r}")

    decimal_separator = _find_decimal_separator(numeric)
    if decimal_separator is None:
        canonical = numeric.replace(",", "").replace(".", "")
    else:
        integer_part, fractional_part = numeric.rsplit(decimal_separator, maxsplit=1)
        integer_part = integer_part.replace(",", "").replace(".", "")
        canonical = f"{integer_part}.{fractional_part}"

    if negative_parentheses:
        canonical = f"-{canonical.lstrip('+')}"

    try:
        return Decimal(canonical)
    except InvalidOperation as error:
        raise NormalizationError(f"invalid price: {raw_price!r}") from error


def _find_decimal_separator(numeric: str) -> str | None:
    """Identify the decimal separator using common price-format conventions."""

    comma_index = numeric.rfind(",")
    dot_index = numeric.rfind(".")
    if comma_index >= 0 and dot_index >= 0:
        return "," if comma_index > dot_index else "."

    separator = "," if comma_index >= 0 else "." if dot_index >= 0 else None
    if separator is None:
        return None

    groups = numeric.lstrip("+-").split(separator)
    if len(groups) == 2 and len(groups[-1]) in {1, 2}:
        return separator
    if len(groups) > 2 and len(groups[-1]) in {1, 2}:
        return separator
    return None


def normalize_currency(
    raw_currency: str | None,
    raw_price: str | None = None,
) -> str:
    """Normalize a currency code or infer it from a supported price symbol."""

    currency_symbols = {"$": "USD", "€": "EUR", "£": "GBP"}
    candidates = (raw_currency, raw_price)
    for candidate in candidates:
        if candidate is None:
            continue
        for symbol, code in currency_symbols.items():
            if symbol in candidate:
                return code

    normalized = normalize_text(raw_currency)
    if normalized is None:
        raise NormalizationError("currency is missing and cannot be inferred from price")

    code = normalized.upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise NormalizationError(f"invalid currency: {raw_currency!r}")
    return code


def normalize_availability(raw_value: str) -> str:
    """Map common availability labels to stable machine-readable values."""

    normalized = normalize_text(raw_value)
    if normalized is None:
        raise NormalizationError("availability is missing")

    value = normalized.casefold()
    if "limited" in value or "low stock" in value:
        return "limited"
    if any(label in value for label in ("out of stock", "sold out", "unavailable")):
        return "out_of_stock"
    if any(label in value for label in ("in stock", "available")):
        return "in_stock"

    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def normalize_rating(raw_value: str | None) -> float | None:
    """Extract the first numeric rating from a textual label."""

    normalized = normalize_text(raw_value)
    if normalized is None:
        return None

    match = re.search(r"[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)", normalized)
    if match is None:
        raise NormalizationError(f"invalid rating: {raw_value!r}")

    try:
        return float(match.group().replace(",", "."))
    except ValueError as error:
        raise NormalizationError(f"invalid rating: {raw_value!r}") from error


def normalize_url(raw_url: str | None, base_url: str) -> str | None:
    """Resolve a possibly relative URL against the catalog base URL."""

    normalized = normalize_text(raw_url)
    if normalized is None:
        return None
    return urljoin(base_url, normalized)
