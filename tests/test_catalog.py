"""Unit tests for bounded dynamic catalog loading with fake Playwright objects."""

from __future__ import annotations

import logging
from typing import cast

import pytest
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.config import Settings
from app.scraper.catalog import CatalogLoadError, CatalogScraper, CatalogStopReason
from app.scraper.selectors import CatalogSelectors, DetailPageSelectors


class FakeCatalogPage:
    """A minimal page fake that models card growth after Load More clicks."""

    def __init__(
        self,
        *,
        card_count: int = 1,
        button_visible: bool = True,
        button_enabled: bool = True,
        wait_outcome: str = "grow",
        hide_button_after_click: bool = False,
    ) -> None:
        self.card_count = card_count
        self.button_visible = button_visible
        self.button_enabled = button_enabled
        self.wait_outcome = wait_outcome
        self.hide_button_after_click = hide_button_after_click
        self.goto_url: str | None = None
        self.click_count = 0
        self.wait_arguments: tuple[str, object, int] | None = None

    def locator(self, selector: str) -> FakeLocator:
        """Return a card or Load More locator based on the selector."""

        if selector == CatalogSelectors().product_card:
            return FakeLocator(self, "cards")
        return FakeLocator(self, "button")

    async def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,
    ) -> None:
        """Record catalog navigation arguments."""

        del wait_until, timeout
        self.goto_url = url

    async def evaluate(self, expression: str) -> None:
        """Accept the expected scrolling script."""

        assert "scrollTo" in expression

    async def wait_for_function(
        self,
        expression: str,
        *,
        arg: object,
        timeout: int,
    ) -> None:
        """Simulate growth, no growth, or a bounded wait timeout."""

        self.wait_arguments = (expression, arg, timeout)
        if self.wait_outcome == "timeout":
            raise PlaywrightTimeoutError("card growth timed out")
        if self.wait_outcome == "grow":
            self.card_count += 1
        if self.hide_button_after_click:
            self.button_visible = False


class FakeLocator:
    """A minimal locator fake for cards and the Load More control."""

    def __init__(self, page: FakeCatalogPage, kind: str) -> None:
        self._page = page
        self._kind = kind

    @property
    def first(self) -> FakeLocator:
        """Return this fake as the first card locator."""

        return self

    async def wait_for(self, *, state: str, timeout: int) -> None:
        """Resolve only when the initial catalog has a visible card."""

        del state, timeout
        if self._kind == "cards" and self._page.card_count == 0:
            raise PlaywrightTimeoutError("no cards")

    async def count(self) -> int:
        """Return the current simulated product card count."""

        return self._page.card_count

    async def is_visible(self) -> bool:
        """Return the configured button visibility."""

        return self._page.button_visible

    async def is_enabled(self) -> bool:
        """Return the configured button enabled state."""

        return self._page.button_enabled

    async def click(self) -> None:
        """Record a Load More click."""

        self._page.click_count += 1


def make_scraper(page: FakeCatalogPage, **settings_overrides: object) -> CatalogScraper:
    """Construct a scraper with fake page dependencies and test settings."""

    values: dict[str, object] = {
        "catalog_url": "https://example.test/catalog",
        "max_load_more_clicks": 3,
        "page_timeout_ms": 100,
    }
    values.update(settings_overrides)
    settings = Settings.model_validate(values)
    return CatalogScraper(
        cast(Page, page),
        CatalogSelectors(),
        DetailPageSelectors(),
        settings,
        logging.getLogger("test.catalog"),
    )


async def test_catalog_loading_waits_for_card_count_growth() -> None:
    """An AJAX card-count increase is observed before the next loop iteration."""

    page = FakeCatalogPage(hide_button_after_click=True)
    result = await make_scraper(page).load_catalog()

    assert page.goto_url == "https://example.test/catalog"
    assert page.wait_arguments is not None
    assert result.initial_card_count == 1
    assert result.final_card_count == 2
    assert result.load_more_click_count == 1
    assert result.stop_reason == CatalogStopReason.LOAD_MORE_DISAPPEARED


async def test_catalog_loading_stops_when_button_disappears() -> None:
    """No click is attempted after Load More disappears."""

    page = FakeCatalogPage(button_visible=False)

    result = await make_scraper(page).load_catalog()

    assert result.stop_reason == CatalogStopReason.LOAD_MORE_DISAPPEARED
    assert result.load_more_click_count == 0


async def test_catalog_loading_stops_when_button_is_disabled() -> None:
    """No click is attempted for a disabled Load More button."""

    page = FakeCatalogPage(button_enabled=False)

    result = await make_scraper(page).load_catalog()

    assert result.stop_reason == CatalogStopReason.LOAD_MORE_DISABLED
    assert result.load_more_click_count == 0


async def test_catalog_loading_stops_when_count_does_not_increase() -> None:
    """A completed wait with unchanged card count prevents an infinite loop."""

    page = FakeCatalogPage(wait_outcome="same")

    result = await make_scraper(page).load_catalog()

    assert result.stop_reason == CatalogStopReason.CARD_COUNT_DID_NOT_GROW
    assert result.load_more_click_count == 1


async def test_catalog_loading_respects_maximum_click_limit() -> None:
    """Loading stops after the configured number of successful Load More clicks."""

    page = FakeCatalogPage()

    result = await make_scraper(page, max_load_more_clicks=1).load_catalog()

    assert result.stop_reason == CatalogStopReason.MAX_LOAD_MORE_CLICKS
    assert result.load_more_click_count == 1
    assert result.final_card_count == 2


async def test_catalog_loading_respects_maximum_item_limit() -> None:
    """A catalog at its configured item limit does not click Load More."""

    page = FakeCatalogPage(card_count=2)

    result = await make_scraper(page, max_items=2).load_catalog()

    assert result.stop_reason == CatalogStopReason.MAX_ITEMS_REACHED
    assert result.load_more_click_count == 0


async def test_catalog_loading_rejects_an_initially_empty_catalog() -> None:
    """No initial visible card produces a clear catalog loading error."""

    page = FakeCatalogPage(card_count=0)

    with pytest.raises(CatalogLoadError, match="initial product card"):
        await make_scraper(page).load_catalog()


async def test_catalog_loading_stops_on_card_growth_timeout() -> None:
    """A Playwright timeout after clicking Load More yields a bounded result."""

    page = FakeCatalogPage(wait_outcome="timeout")

    result = await make_scraper(page).load_catalog()

    assert result.stop_reason == CatalogStopReason.CARD_GROWTH_TIMEOUT
    assert result.final_card_count == 1
    assert result.load_more_click_count == 1
