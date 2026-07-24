"""Comparison of product snapshots from separate catalog runs."""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit, urlunsplit

from app.models import AvailabilityChange, ComparisonResult, PriceChange, Product


def calculate_change_percent(
    old_value: Decimal,
    new_value: Decimal,
) -> Decimal | None:
    """Return the signed percent change rounded to two places, if defined."""

    if old_value == Decimal("0"):
        return None
    return ((new_value - old_value) / old_value * Decimal("100")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def compare_snapshots(
    previous_products: Iterable[Product],
    current_products: Iterable[Product],
) -> ComparisonResult:
    """Compare snapshots and classify new, removed, changed, and unchanged products."""

    previous_by_identity = _products_by_identity(previous_products)
    current_by_identity = _products_by_identity(current_products)

    new_products = [
        product
        for identity, product in current_by_identity.items()
        if identity not in previous_by_identity
    ]
    removed_products = [
        product
        for identity, product in previous_by_identity.items()
        if identity not in current_by_identity
    ]
    price_changes: list[PriceChange] = []
    availability_changes: list[AvailabilityChange] = []
    unchanged_products: list[Product] = []

    for identity, current_product in current_by_identity.items():
        previous_product = previous_by_identity.get(identity)
        if previous_product is None:
            continue

        price_changed = previous_product.price != current_product.price
        availability_changed = previous_product.availability != current_product.availability
        if price_changed:
            price_changes.append(_price_change(previous_product, current_product))
        if availability_changed:
            availability_changes.append(
                AvailabilityChange(
                    product_id=current_product.product_id,
                    product_title=current_product.title,
                    previous_status=previous_product.availability,
                    current_status=current_product.availability,
                    product_url=current_product.product_url,
                )
            )
        if not price_changed and not availability_changed:
            unchanged_products.append(current_product)

    return ComparisonResult(
        new_products=new_products,
        removed_products=removed_products,
        price_changes=price_changes,
        availability_changes=availability_changes,
        unchanged_products=unchanged_products,
    )


def _products_by_identity(products: Iterable[Product]) -> dict[str, Product]:
    """Index products by primary ID and URL fallback, retaining the first record."""

    indexed: dict[str, Product] = {}
    for product in products:
        indexed.setdefault(_comparison_identity(product), product)
    return indexed


def _comparison_identity(product: Product) -> str:
    """Return an ID key, or a normalized URL key for incomplete legacy data."""

    product_id = product.product_id.strip()
    if product_id:
        return f"id:{product_id}"
    return f"url:{_normalized_url(str(product.product_url))}"


def _normalized_url(value: str) -> str:
    """Normalize URL casing and trailing slashes for identity fallback."""

    parsed = urlsplit(value)
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, ""))


def _price_change(previous_product: Product, current_product: Product) -> PriceChange:
    """Build the complete reporting record for a product price change."""

    return PriceChange(
        product_id=current_product.product_id,
        product_title=current_product.title,
        old_price=previous_product.price,
        new_price=current_product.price,
        absolute_difference=abs(current_product.price - previous_product.price),
        percentage_difference=calculate_change_percent(
            previous_product.price,
            current_product.price,
        ),
        currency=current_product.currency,
        product_url=current_product.product_url,
    )
