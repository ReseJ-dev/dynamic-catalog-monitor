"""Scraper profile for the public Scraping Sandbox pagination interface."""

from __future__ import annotations

from datetime import UTC, datetime

from playwright.async_api import Locator
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.models import RawProduct
from app.scraper.catalog import CatalogLoadError, CatalogScraper


class ScrapingSandboxScraper(CatalogScraper):
    """Collect bounded paginated cards from Scraping Sandbox without live-site tests."""

    _next_page_button = "button[data-slot='button']:has(svg.lucide-chevron-right)"

    async def collect_products(self) -> list[RawProduct]:
        """Collect cards across Sandbox pages, respecting the configured item limit."""

        await self.navigate_to_catalog()
        cards = self._page.locator(self._catalog_selectors.product_card)
        await self._wait_for_initial_cards(cards)
        timestamp = datetime.now(UTC)
        products: list[RawProduct] = []
        page_turns = 0

        while True:
            products.extend(await self._current_page_products(timestamp, len(products)))
            if self._settings.max_items is not None and len(products) >= self._settings.max_items:
                return products
            if page_turns >= self._settings.max_load_more_clicks:
                return products

            next_button = self._page.locator(self._next_page_button)
            if not await next_button.is_visible() or not await next_button.is_enabled():
                return products
            previous_first_href = await self._first_card_href(cards)
            await next_button.click()
            page_turns += 1
            try:
                await self._wait_for_page_change(previous_first_href)
            except PlaywrightTimeoutError:
                self._logger.warning(
                    "Sandbox pagination stopped because the next page did not render"
                )
                return products

    async def _current_page_products(
        self,
        timestamp: datetime,
        collected_count: int,
    ) -> list[RawProduct]:
        """Extract only the remaining allowed card records from the active page."""

        cards = self._page.locator(self._catalog_selectors.product_card)
        card_count = await cards.count()
        if self._settings.max_items is None:
            limit = card_count
        else:
            limit = min(card_count, self._settings.max_items - collected_count)
        return [
            await self._extract_card_product(cards.nth(index), timestamp) for index in range(limit)
        ]

    async def _first_card_href(self, cards: Locator) -> str | None:
        """Read the first card link to detect client-side pagination replacement."""

        if await cards.count() == 0:
            raise CatalogLoadError("catalog did not contain an initial product card")
        return await cards.first.get_attribute("href")

    async def _wait_for_page_change(self, previous_first_href: str | None) -> None:
        """Wait until the first Sandbox product link changes after pagination."""

        await self._page.wait_for_function(
            """
            ({ selector, previousHref }) =>
                document.querySelector(selector)?.getAttribute('href') !== previousHref
            """,
            arg={
                "selector": self._catalog_selectors.product_card,
                "previousHref": previous_first_href,
            },
            timeout=self._settings.page_timeout_ms,
        )
