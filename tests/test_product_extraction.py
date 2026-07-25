"""Unit tests for card extraction and sequential detail-page enrichment."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from playwright.async_api import Page

from app.config import Settings
from app.scraper.catalog import CatalogScraper
from app.scraper.selectors import CatalogSelectors, DetailPageSelectors

RUN_TIMESTAMP = datetime(2026, 7, 25, 16, 0, tzinfo=UTC)


class FakeNode:
    """A small DOM-like node for selector and attribute extraction tests."""

    def __init__(
        self,
        *,
        text: str | None = None,
        attributes: dict[str, str] | None = None,
        children: dict[str, FakeNode] | None = None,
    ) -> None:
        self.text = text
        self.attributes = attributes or {}
        self.children = children or {}


class FakeLocator:
    """A locator fake backed by a fixed list of fake nodes."""

    def __init__(self, nodes: list[FakeNode]) -> None:
        self._nodes = nodes

    @property
    def first(self) -> FakeLocator:
        """Return the first matching fake node as a locator."""

        return FakeLocator(self._nodes[:1])

    def nth(self, index: int) -> FakeLocator:
        """Return the indexed fake node as a locator."""

        return FakeLocator(self._nodes[index : index + 1])

    def locator(self, selector: str) -> FakeLocator:
        """Return descendants matching a selector from all current nodes."""

        return FakeLocator(
            [node.children[selector] for node in self._nodes if selector in node.children]
        )

    async def count(self) -> int:
        """Return the number of matched fake nodes."""

        return len(self._nodes)

    async def text_content(self) -> str | None:
        """Return the first node's text content."""

        return self._nodes[0].text if self._nodes else None

    async def get_attribute(self, name: str) -> str | None:
        """Return the first node's requested attribute."""

        return self._nodes[0].attributes.get(name) if self._nodes else None


class FakeExtractionPage:
    """A page fake that serves catalog cards and detail pages by URL."""

    def __init__(self, cards: list[FakeNode], details: dict[str, FakeNode]) -> None:
        self.cards = cards
        self.details = details
        self.current_detail: FakeNode | None = None
        self.goto_urls: list[str] = []

    def locator(self, selector: str) -> FakeLocator:
        """Return cards on the catalog page or fields on the active detail page."""

        if self.current_detail is None:
            if selector == CatalogSelectors().product_card:
                return FakeLocator(self.cards)
            return FakeLocator([])
        if selector == DetailPageSelectors().canonical_product_id:
            return FakeLocator([self.current_detail])
        child = self.current_detail.children.get(selector)
        return FakeLocator([child] if child is not None else [])

    async def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> None:
        """Switch to a detail page or fail for an unavailable one."""

        del wait_until, timeout
        self.goto_urls.append(url)
        detail = self.details.get(url)
        if detail is None:
            raise RuntimeError("detail page unavailable")
        self.current_detail = detail


def card_node(
    *,
    product_id: str | None = "card-001",
    title: str | None = "Card Product",
    product_url: str | None = "/products/card-001",
    image_url: str | None = "/images/card-thumb.jpg",
) -> FakeNode:
    """Build a product card with optional required and optional fields."""

    selectors = CatalogSelectors()
    children: dict[str, FakeNode] = {}
    values = {
        selectors.product_title: title,
        selectors.product_category: "Fixtures",
        selectors.product_price: "$19.99",
        selectors.product_currency: "USD",
        selectors.product_availability: "In Stock",
        selectors.product_rating: "4.2 out of 5",
    }
    for selector, value in values.items():
        if value is not None:
            children[selector] = FakeNode(text=value)
    if image_url is not None:
        children[selectors.product_image] = FakeNode(attributes={"src": image_url})
    if product_url is not None:
        children[selectors.product_link] = FakeNode(attributes={"href": product_url})
    attributes = {"data-product-id": product_id} if product_id is not None else {}
    return FakeNode(attributes=attributes, children=children)


def detail_node() -> FakeNode:
    """Build a detail page whose values supersede card-level information."""

    selectors = DetailPageSelectors()
    return FakeNode(
        attributes={"data-product-id": "canonical-001"},
        children={
            selectors.canonical_product_url: FakeNode(
                attributes={"href": "/products/canonical-001"}
            ),
            selectors.availability: FakeNode(text="Limited availability"),
            selectors.rating: FakeNode(text="4.8 out of 5"),
            selectors.description: FakeNode(text="Full product description."),
            selectors.image: FakeNode(attributes={"src": "/images/canonical-full.jpg"}),
        },
    )


def make_scraper(
    page: FakeExtractionPage,
    **settings_overrides: object,
) -> CatalogScraper:
    """Create an extraction scraper backed by a fake page."""

    values: dict[str, object] = {
        "catalog_url": "https://example.test/catalog",
        "page_timeout_ms": 100,
    }
    values.update(settings_overrides)
    return CatalogScraper(
        cast(Page, page),
        CatalogSelectors(),
        DetailPageSelectors(),
        Settings.model_validate(values),
        logging.getLogger("test.extraction"),
    )


async def test_extract_card_products_collects_raw_fields_and_relative_urls() -> None:
    """Card extraction preserves raw values and resolves relative links."""

    scraper = make_scraper(FakeExtractionPage([card_node()], {}))

    products = await scraper.extract_card_products(scraped_at=RUN_TIMESTAMP)

    assert len(products) == 1
    product = products[0]
    assert product.product_id == "card-001"
    assert product.title == "Card Product"
    assert product.category == "Fixtures"
    assert product.price == "$19.99"
    assert product.currency == "USD"
    assert product.availability == "In Stock"
    assert product.rating == "4.2 out of 5"
    assert product.image_url == "https://example.test/images/card-thumb.jpg"
    assert product.product_url == "https://example.test/products/card-001"
    assert product.scraped_at == RUN_TIMESTAMP


async def test_detail_page_values_enrich_the_card_record() -> None:
    """Authoritative detail fields replace their corresponding card values."""

    page = FakeExtractionPage(
        [card_node()],
        {"https://example.test/products/card-001": detail_node()},
    )

    products = await make_scraper(page).extract_loaded_products(scraped_at=RUN_TIMESTAMP)

    product = products[0]
    assert product.product_id == "canonical-001"
    assert product.product_url == "https://example.test/products/canonical-001"
    assert product.image_url == "https://example.test/images/canonical-full.jpg"
    assert product.availability == "Limited availability"
    assert product.rating == "4.8 out of 5"
    assert product.description == "Full product description."
    assert product.scraped_at == RUN_TIMESTAMP


async def test_missing_optional_fields_return_none() -> None:
    """Absent optional card fields are represented as None without an extraction error."""

    node = card_node(image_url=None)
    node.children.pop(CatalogSelectors().product_category)
    node.children.pop(CatalogSelectors().product_rating)

    product = (await make_scraper(FakeExtractionPage([node], {})).extract_card_products())[0]

    assert product.category is None
    assert product.rating is None
    assert product.image_url is None


async def test_missing_required_fields_are_preserved_for_validation() -> None:
    """The scraper does not reject incomplete cards before the validation layer."""

    product = (
        await make_scraper(
            FakeExtractionPage([card_node(product_id=None, title=None, product_url=None)], {})
        ).extract_loaded_products(scraped_at=RUN_TIMESTAMP)
    )[0]

    assert product.product_id is None
    assert product.title is None
    assert product.product_url is None
    assert product.extraction_warnings == ["detail extraction skipped: product URL is missing"]


async def test_detail_navigation_failure_keeps_card_record_with_warning() -> None:
    """A detail page error retains card values and captures an extraction warning."""

    page = FakeExtractionPage([card_node()], {})

    product = (await make_scraper(page).extract_loaded_products(scraped_at=RUN_TIMESTAMP))[0]

    assert product.product_id == "card-001"
    assert product.product_url == "https://example.test/products/card-001"
    assert product.extraction_warnings == [
        "detail extraction failed: RuntimeError: detail page unavailable"
    ]


async def test_extraction_enforces_maximum_items() -> None:
    """Only the configured number of cards are opened and returned."""

    first = card_node(product_id="card-001", product_url="/products/card-001")
    second = card_node(product_id="card-002", product_url="/products/card-002")
    page = FakeExtractionPage(
        [first, second],
        {"https://example.test/products/card-001": detail_node()},
    )

    products = await make_scraper(page, max_items=1).extract_loaded_products(
        scraped_at=RUN_TIMESTAMP
    )

    assert len(products) == 1
    assert page.goto_urls == ["https://example.test/products/card-001"]


def test_local_html_fixtures_are_available() -> None:
    """The local HTML fixtures document the catalog and detail-page target markup."""

    fixture_dir = Path(__file__).parent / "fixtures"

    assert "product-card" in (fixture_dir / "catalog_cards.html").read_text(encoding="utf-8")
    assert "canonical" in (fixture_dir / "detail_page_enriched.html").read_text(encoding="utf-8")
