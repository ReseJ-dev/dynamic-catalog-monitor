"""Immutable selector groups for catalog and product-detail pages."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogSelectors:
    """Selectors used to extract product cards from the catalog page."""

    product_card: str = "article.product-card"
    product_id: str = "[data-product-id]"
    product_title: str = ".product-title"
    product_category: str = ".product-category"
    product_price: str = ".product-price"
    product_currency: str = ".product-currency"
    product_availability: str = ".product-availability"
    product_rating: str = ".product-rating"
    product_description: str = ".product-description"
    product_image: str = "img.product-image"
    product_link: str = "a.product-link"
    load_more_button: str = "button[data-testid='load-more']"


@dataclass(frozen=True)
class DetailPageSelectors:
    """Selectors used to enrich a product from its detail page."""

    product_id: str = "[data-product-id]"
    title: str = "h1.product-title"
    category: str = ".product-category"
    price: str = ".product-price"
    currency: str = ".product-currency"
    availability: str = ".product-availability"
    rating: str = ".product-rating"
    description: str = ".product-description"
    image: str = "img.product-image"
    canonical_product_id: str = "[data-product-id]"
    canonical_product_url: str = "link[rel='canonical']"


def scraping_sandbox_catalog_selectors() -> CatalogSelectors:
    """Return selectors for the public Scraping Sandbox practice catalog."""

    return CatalogSelectors(
        product_card="a.product-card",
        product_id=".sku",
        product_title=".product-name",
        product_category=".category",
        product_price=".price",
        product_currency=".currency-not-present",
        product_availability=".availability",
        product_rating=".rating",
        product_image="img.product-image",
        product_link="a.product-link-not-present",
        load_more_button="button[data-testid='load-more-not-present']",
    )
