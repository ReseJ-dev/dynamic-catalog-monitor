"""Deterministic deduplication for normalized catalog products."""

from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from app.models import Product


def product_identity(product: Product) -> str:
    """Return the highest-priority stable identity available for a product."""

    product_id = product.product_id.strip()
    if product_id:
        return f"id:{product_id}"

    normalized_url = _normalized_url(str(product.product_url))
    if normalized_url:
        return f"url:{normalized_url}"

    title = " ".join(product.title.casefold().split())
    return f"title-price:{title}:{product.price.normalize()}"


def deduplicate_products(
    products: Iterable[Product],
) -> tuple[list[Product], list[Product]]:
    """Keep one richest product per identity and return rejected duplicates."""

    unique_by_identity: dict[str, Product] = {}
    identity_order: list[str] = []
    duplicates: list[Product] = []

    for product in products:
        identity = product_identity(product)
        existing = unique_by_identity.get(identity)
        if existing is None:
            unique_by_identity[identity] = product
            identity_order.append(identity)
            continue

        if _richness(product) > _richness(existing):
            unique_by_identity[identity] = product
            duplicates.append(existing)
        else:
            duplicates.append(product)

    return [unique_by_identity[identity] for identity in identity_order], duplicates


def _normalized_url(value: str) -> str:
    """Normalize a URL for stable comparison without changing its resource."""

    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, ""))


def _richness(product: Product) -> int:
    """Count populated optional Product fields for duplicate tie-breaking."""

    optional_values = (
        product.category,
        product.rating,
        product.description,
        product.image_url,
    )
    return sum(value is not None for value in optional_values)
