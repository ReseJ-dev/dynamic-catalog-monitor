"""Bounded dynamic catalog loading for Playwright pages."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.config import Settings
from app.models import RawProduct
from app.scraper.selectors import CatalogSelectors, DetailPageSelectors


class CatalogLoadError(RuntimeError):
    """Raised when an initial catalog cannot provide any product cards."""


class CatalogStopReason(StrEnum):
    """Reasons that a bounded catalog-loading loop can finish."""

    LOAD_MORE_DISAPPEARED = "load_more_disappeared"
    LOAD_MORE_DISABLED = "load_more_disabled"
    CARD_COUNT_DID_NOT_GROW = "card_count_did_not_grow"
    CARD_GROWTH_TIMEOUT = "card_growth_timeout"
    MAX_LOAD_MORE_CLICKS = "max_load_more_clicks"
    MAX_ITEMS_REACHED = "max_items_reached"


@dataclass(frozen=True)
class CatalogLoadResult:
    """Counts and termination reason from dynamic catalog loading."""

    initial_card_count: int
    final_card_count: int
    load_more_click_count: int
    stop_reason: CatalogStopReason


async def safe_text(locator: Locator) -> str | None:
    """Return stripped text for an optional element, or ``None`` when absent."""

    try:
        if await locator.count() == 0:
            return None
        value = await locator.first.text_content()
    except PlaywrightError:
        return None
    return value.strip() or None if value is not None else None


async def safe_attribute(locator: Locator, attribute: str) -> str | None:
    """Return a stripped optional element attribute, or ``None`` when absent."""

    try:
        if await locator.count() == 0:
            return None
        value = await locator.first.get_attribute(attribute)
    except PlaywrightError:
        return None
    return value.strip() or None if value is not None else None


def resolve_url(raw_url: str | None, base_url: str) -> str | None:
    """Resolve an optional catalog URL relative to the configured catalog URL."""

    if raw_url is None:
        return None
    return urljoin(base_url, raw_url)


class CatalogScraper:
    """Navigate a catalog page and load cards until a bounded stop condition."""

    def __init__(
        self,
        page: Page,
        catalog_selectors: CatalogSelectors,
        detail_selectors: DetailPageSelectors,
        settings: Settings,
        logger: logging.Logger,
    ) -> None:
        """Store the page, selectors, settings, and logger for one collection run."""

        self._page = page
        self._catalog_selectors = catalog_selectors
        self._detail_selectors = detail_selectors
        self._settings = settings
        self._logger = logger

    async def load_catalog(self) -> CatalogLoadResult:
        """Navigate to the catalog and load cards until an explicit stop condition."""

        await self.navigate_to_catalog()
        cards = self._page.locator(self._catalog_selectors.product_card)
        initial_count = await self._wait_for_initial_cards(cards)
        click_count = 0

        while True:
            current_count = await cards.count()
            stop_reason = self._limit_stop_reason(current_count, click_count)
            if stop_reason is not None:
                return CatalogLoadResult(initial_count, current_count, click_count, stop_reason)

            await self._scroll_for_more_cards()
            load_more_button = self._page.locator(self._catalog_selectors.load_more_button)
            stop_reason = await self._load_more_stop_reason(load_more_button)
            if stop_reason is not None:
                return CatalogLoadResult(initial_count, current_count, click_count, stop_reason)

            previous_count = current_count
            await load_more_button.click()
            click_count += 1
            self._logger.info(
                "Catalog load iteration %d: waiting for cards to exceed %d",
                click_count,
                previous_count,
            )

            try:
                await self._wait_for_card_growth(previous_count)
            except PlaywrightTimeoutError:
                final_count = await cards.count()
                return CatalogLoadResult(
                    initial_count,
                    final_count,
                    click_count,
                    CatalogStopReason.CARD_GROWTH_TIMEOUT,
                )

            final_count = await cards.count()
            if final_count <= previous_count:
                return CatalogLoadResult(
                    initial_count,
                    final_count,
                    click_count,
                    CatalogStopReason.CARD_COUNT_DID_NOT_GROW,
                )

    async def collect_products(self) -> list[RawProduct]:
        """Load the catalog and return sequentially enriched raw product records."""

        await self.load_catalog()
        return await self.extract_loaded_products(scraped_at=datetime.now(UTC))

    async def collect_raw_products(self) -> list[RawProduct]:
        """Return raw products using an explicit name for pipeline callers."""

        return await self.collect_products()

    async def extract_loaded_products(
        self, *, scraped_at: datetime | None = None
    ) -> list[RawProduct]:
        """Extract cards already on the page and enrich each detail page sequentially."""

        run_timestamp = scraped_at or datetime.now(UTC)
        card_products = await self.extract_card_products(scraped_at=run_timestamp)
        enriched_products: list[RawProduct] = []
        for product in card_products:
            enriched_products.append(await self.enrich_product_details(product))
        return enriched_products

    async def extract_card_products(
        self, *, scraped_at: datetime | None = None
    ) -> list[RawProduct]:
        """Extract raw card-level fields from the currently loaded catalog cards."""

        run_timestamp = scraped_at or datetime.now(UTC)
        cards = self._page.locator(self._catalog_selectors.product_card)
        card_count = await cards.count()
        limit = self._settings.max_items
        item_count = min(card_count, limit) if limit is not None else card_count
        products: list[RawProduct] = []
        for index in range(item_count):
            products.append(await self._extract_card_product(cards.nth(index), run_timestamp))
        return products

    async def enrich_product_details(self, product: RawProduct) -> RawProduct:
        """Enrich a card record from its detail page without discarding card data on failure."""

        if product.product_url is None:
            return self._with_warning(product, "detail extraction skipped: product URL is missing")

        try:
            await self._page.goto(
                product.product_url,
                wait_until="domcontentloaded",
                timeout=self._settings.page_timeout_ms,
            )
            detail_id = await self._identifier_from_locator(
                self._page.locator(self._detail_selectors.canonical_product_id)
            )
            canonical_url = resolve_url(
                await safe_attribute(
                    self._page.locator(self._detail_selectors.canonical_product_url),
                    "href",
                ),
                str(self._settings.catalog_url),
            )
            detail_values = {
                "product_id": detail_id or product.product_id,
                "availability": await safe_text(
                    self._page.locator(self._detail_selectors.availability)
                )
                or product.availability,
                "rating": await safe_text(self._page.locator(self._detail_selectors.rating))
                or product.rating,
                "description": await safe_text(
                    self._page.locator(self._detail_selectors.description)
                )
                or product.description,
                "image_url": resolve_url(
                    await safe_attribute(self._page.locator(self._detail_selectors.image), "src"),
                    str(self._settings.catalog_url),
                )
                or product.image_url,
                "product_url": canonical_url or product.product_url,
            }
            return product.model_copy(update=detail_values)
        except Exception as error:
            self._logger.warning(
                "Unable to enrich product detail page %s: %s", product.product_url, error
            )
            return self._with_warning(
                product, f"detail extraction failed: {type(error).__name__}: {error}"
            )

    async def _extract_card_product(self, card: Locator, scraped_at: datetime) -> RawProduct:
        """Extract every immediately available raw field from one product card."""

        return RawProduct(
            product_id=await self._identifier_from_locator(card),
            title=await safe_text(card.locator(self._catalog_selectors.product_title)),
            category=await safe_text(card.locator(self._catalog_selectors.product_category)),
            price=await safe_text(card.locator(self._catalog_selectors.product_price)),
            currency=await safe_text(card.locator(self._catalog_selectors.product_currency)),
            availability=await safe_text(
                card.locator(self._catalog_selectors.product_availability)
            ),
            rating=await safe_text(card.locator(self._catalog_selectors.product_rating)),
            image_url=resolve_url(
                await safe_attribute(card.locator(self._catalog_selectors.product_image), "src"),
                str(self._settings.catalog_url),
            ),
            product_url=resolve_url(
                await safe_attribute(card.locator(self._catalog_selectors.product_link), "href"),
                str(self._settings.catalog_url),
            ),
            scraped_at=scraped_at,
        )

    async def _identifier_from_locator(self, locator: Locator) -> str | None:
        """Extract a product ID from a data attribute or text content."""

        return await safe_attribute(locator, "data-product-id") or await safe_text(locator)

    @staticmethod
    def _with_warning(product: RawProduct, warning: str) -> RawProduct:
        """Return a copy of a raw product with one extraction warning appended."""

        return product.model_copy(
            update={"extraction_warnings": [*product.extraction_warnings, warning]}
        )

    async def navigate_to_catalog(self) -> None:
        """Navigate to the configured catalog URL and wait for DOM readiness."""

        self._logger.info("Navigating to catalog: %s", self._settings.catalog_url)
        await self._page.goto(
            str(self._settings.catalog_url),
            wait_until="domcontentloaded",
            timeout=self._settings.page_timeout_ms,
        )

    async def _wait_for_initial_cards(self, cards: Locator) -> int:
        """Wait for one visible card and return the initial card count."""

        try:
            await cards.first.wait_for(
                state="visible",
                timeout=self._settings.page_timeout_ms,
            )
        except PlaywrightTimeoutError as error:
            raise CatalogLoadError("catalog did not contain an initial product card") from error

        initial_count = await cards.count()
        if initial_count < 1:
            raise CatalogLoadError("catalog did not contain an initial product card")
        return initial_count

    def _limit_stop_reason(
        self,
        card_count: int,
        click_count: int,
    ) -> CatalogStopReason | None:
        """Return a configured item or click limit that has already been reached."""

        if self._settings.max_items is not None and card_count >= self._settings.max_items:
            return CatalogStopReason.MAX_ITEMS_REACHED
        if click_count >= self._settings.max_load_more_clicks:
            return CatalogStopReason.MAX_LOAD_MORE_CLICKS
        return None

    async def _load_more_stop_reason(self, button: Locator) -> CatalogStopReason | None:
        """Return a stop reason when the Load More control is unavailable."""

        if not await button.is_visible():
            return CatalogStopReason.LOAD_MORE_DISAPPEARED
        if not await button.is_enabled():
            return CatalogStopReason.LOAD_MORE_DISABLED
        return None

    async def _scroll_for_more_cards(self) -> None:
        """Scroll to prompt lazy-loaded pages to expose their Load More control."""

        await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    async def _wait_for_card_growth(self, previous_count: int) -> None:
        """Await an AJAX or DOM update that increases the product card count."""

        await self._page.wait_for_function(
            """
            ({ previousCount, selector }) =>
                document.querySelectorAll(selector).length > previousCount
            """,
            arg={
                "previousCount": previous_count,
                "selector": self._catalog_selectors.product_card,
            },
            timeout=self._settings.page_timeout_ms,
        )
