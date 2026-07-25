"""Bounded dynamic catalog loading for Playwright pages."""

import logging
from dataclasses import dataclass
from enum import StrEnum

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.config import Settings
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
