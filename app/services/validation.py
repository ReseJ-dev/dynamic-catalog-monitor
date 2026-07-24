"""Conversion of raw scraper records into validated products."""

from collections.abc import Callable, Iterable
from datetime import datetime

from pydantic import ValidationError

from app.models import InvalidRecord, Product, RawProduct
from app.services.normalization import (
    NormalizationError,
    normalize_availability,
    normalize_currency,
    normalize_price,
    normalize_rating,
    normalize_text,
    normalize_url,
)

ErrorDetail = dict[str, object]


class ProductValidationError(ValueError):
    """A product validation failure with structured field-level details."""

    def __init__(self, details: list[ErrorDetail]) -> None:
        self.details = details
        reasons = "; ".join(f"{detail['field']}: {detail['message']}" for detail in details)
        super().__init__(f"product validation failed: {reasons}")


def validate_raw_product(
    raw_product: RawProduct,
    *,
    base_url: str,
    scraped_at: datetime,
) -> Product:
    """Normalize one raw record and construct a validated product."""

    details: list[ErrorDetail] = []
    product_id = normalize_text(raw_product.product_id)
    title = normalize_text(raw_product.title)
    category = normalize_text(raw_product.category)
    description = normalize_text(raw_product.description)
    product_url = normalize_url(raw_product.product_url, base_url)
    image_url = normalize_url(raw_product.image_url, base_url)

    if product_id is None:
        details.append(_error_detail("product_id", "product ID is missing", "missing"))
    if title is None:
        details.append(_error_detail("title", "title is missing", "missing"))
    if product_url is None:
        details.append(_error_detail("product_url", "product URL is missing", "missing"))

    price = _normalize_with_details(
        "price",
        lambda: normalize_price(raw_product.price or ""),
        details,
    )
    currency = _normalize_with_details(
        "currency",
        lambda: normalize_currency(raw_product.currency, raw_product.price),
        details,
    )
    availability = _normalize_with_details(
        "availability",
        lambda: normalize_availability(raw_product.availability or ""),
        details,
    )
    rating = _normalize_with_details(
        "rating",
        lambda: normalize_rating(raw_product.rating),
        details,
    )

    if details:
        raise ProductValidationError(details)

    values: dict[str, object] = {
        "product_id": product_id,
        "title": title,
        "category": category,
        "price": price,
        "currency": currency,
        "availability": availability,
        "rating": rating,
        "description": description,
        "image_url": image_url,
        "product_url": product_url,
        "scraped_at": scraped_at,
    }
    try:
        return Product.model_validate(values)
    except ValidationError as error:
        raise ProductValidationError(_pydantic_error_details(error)) from error


def validate_products(
    raw_products: Iterable[RawProduct],
    *,
    base_url: str,
    scraped_at: datetime,
) -> tuple[list[Product], list[InvalidRecord]]:
    """Separate raw records into valid products and preserved invalid records."""

    valid_products: list[Product] = []
    invalid_records: list[InvalidRecord] = []

    for raw_product in raw_products:
        try:
            product = validate_raw_product(
                raw_product,
                base_url=base_url,
                scraped_at=scraped_at,
            )
        except ProductValidationError as error:
            invalid_records.append(
                InvalidRecord(
                    raw_product=raw_product,
                    reason=str(error),
                    errors=error.details,
                )
            )
        else:
            valid_products.append(product)

    return valid_products, invalid_records


def _normalize_with_details(
    field_name: str,
    normalizer: Callable[[], object],
    details: list[ErrorDetail],
) -> object:
    """Run a zero-argument normalizer and retain its domain error."""

    try:
        return normalizer()
    except NormalizationError as error:
        details.append(_error_detail(field_name, str(error), "normalization_error"))
        return None


def _error_detail(field: str, message: str, error_type: str) -> ErrorDetail:
    """Build a consistent structured validation error."""

    return {"field": field, "message": message, "type": error_type}


def _pydantic_error_details(error: ValidationError) -> list[ErrorDetail]:
    """Convert Pydantic errors into stable application-level details."""

    details: list[ErrorDetail] = []
    for item in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = ".".join(str(part) for part in item["loc"])
        details.append(
            _error_detail(
                location or "product",
                str(item["msg"]),
                str(item["type"]),
            )
        )
    return details
