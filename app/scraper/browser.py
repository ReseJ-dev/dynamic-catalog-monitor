"""Asynchronous Playwright browser lifecycle helpers."""

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, cast

from playwright._impl._api_structures import ViewportSize
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class PlaywrightStarter(Protocol):
    """The Playwright factory result needed by the browser manager."""

    async def start(self) -> Playwright:
        """Start and return a Playwright instance."""


class BrowserManager:
    """Own Playwright, Chromium, a context, and one page for a scraping run."""

    def __init__(
        self,
        *,
        headless: bool,
        timeout_ms: int,
        user_agent: str | None = DEFAULT_USER_AGENT,
        viewport: dict[str, int] | None = None,
        locale: str | None = "en-US",
        playwright_factory: Callable[[], PlaywrightStarter] | None = None,
    ) -> None:
        """Store browser settings without allocating external resources."""

        self._headless = headless
        self._timeout_ms = timeout_ms
        self._user_agent = user_agent
        self._viewport = viewport or {"width": 1440, "height": 900}
        self._locale = locale
        self._playwright_factory = playwright_factory or cast(
            Callable[[], PlaywrightStarter],
            async_playwright,
        )
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        """Return the page after the manager has started."""

        if self._page is None:
            raise RuntimeError("browser manager has not been started")
        return self._page

    async def __aenter__(self) -> "BrowserManager":
        """Start Playwright and create a configured Chromium page."""

        try:
            self._playwright = await self._playwright_factory().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)
            self._context = await self._browser.new_context(
                viewport=cast(ViewportSize, self._viewport),
                user_agent=self._user_agent,
                locale=self._locale,
            )
            self._page = await self._context.new_page()
            self._page.set_default_timeout(self._timeout_ms)
            return self
        except Exception:
            await self.close()
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Release resources while preserving an exception from the with-block."""

        del exc_type, exc_value, traceback
        await self.close()

    async def close(self) -> None:
        """Close all allocated resources, continuing after individual cleanup failures."""

        page, self._page = self._page, None
        context, self._context = self._context, None
        browser, self._browser = self._browser, None
        playwright, self._playwright = self._playwright, None

        if page is not None:
            await _close_resource("page", page.close)
        if context is not None:
            await _close_resource("browser context", context.close)
        if browser is not None:
            await _close_resource("browser", browser.close)
        if playwright is not None:
            await _close_resource("Playwright", playwright.stop)


async def _close_resource(name: str, close: Callable[[], Awaitable[None]]) -> None:
    """Close one Playwright resource without masking an earlier failure."""

    try:
        await close()
    except Exception:
        LOGGER.exception("Unable to close %s", name)
