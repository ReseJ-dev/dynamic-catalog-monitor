"""Unit tests for browser lifecycle management without starting Chromium."""

from collections.abc import Callable
from typing import cast

import pytest

from app.scraper.browser import BrowserManager, PlaywrightStarter


class FakePage:
    """A fake page that records timeout and cleanup calls."""

    def __init__(self) -> None:
        self.default_timeout: int | None = None
        self.closed = False

    def set_default_timeout(self, timeout: int) -> None:
        """Record the configured timeout."""

        self.default_timeout = timeout

    async def close(self) -> None:
        """Record page closure."""

        self.closed = True


class FakeContext:
    """A fake browser context containing one page."""

    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False

    async def new_page(self) -> FakePage:
        """Return the configured fake page."""

        return self.page

    async def close(self) -> None:
        """Record context closure."""

        self.closed = True


class FakeBrowser:
    """A fake Chromium browser that records context options."""

    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.context_options: dict[str, object] | None = None
        self.closed = False

    async def new_context(self, **options: object) -> FakeContext:
        """Record context options and return the fake context."""

        self.context_options = options
        return self.context

    async def close(self) -> None:
        """Record browser closure."""

        self.closed = True


class FakeChromium:
    """A fake Chromium launcher that records the headless option."""

    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.headless: bool | None = None

    async def launch(self, *, headless: bool) -> FakeBrowser:
        """Record headless mode and return the fake browser."""

        self.headless = headless
        return self.browser


class FakePlaywright:
    """A fake Playwright instance exposing Chromium and stop."""

    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    async def stop(self) -> None:
        """Record Playwright shutdown."""

        self.stopped = True


class FakePlaywrightStarter:
    """A fake Playwright context manager with an async start method."""

    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> FakePlaywright:
        """Return the fake Playwright instance."""

        return self.playwright


def make_browser_manager() -> tuple[BrowserManager, FakePage, FakeBrowser, FakePlaywright]:
    """Create a browser manager with fully fake Playwright dependencies."""

    page = FakePage()
    browser = FakeBrowser(FakeContext(page))
    playwright = FakePlaywright(FakeChromium(browser))
    starter = FakePlaywrightStarter(playwright)
    factory = cast(Callable[[], PlaywrightStarter], lambda: starter)
    manager = BrowserManager(
        headless=False,
        timeout_ms=12_345,
        user_agent="test-agent",
        viewport={"width": 1000, "height": 700},
        locale="en-GB",
        playwright_factory=factory,
    )
    return manager, page, browser, playwright


async def test_browser_manager_creates_configured_page_and_closes_resources() -> None:
    """The manager launches Chromium, configures one page, and cleans up."""

    manager, page, browser, playwright = make_browser_manager()

    async with manager as active_manager:
        assert active_manager.page is cast(object, page)
        assert page.default_timeout == 12_345
        assert playwright.chromium.headless is False
        assert browser.context_options == {
            "viewport": {"width": 1000, "height": 700},
            "user_agent": "test-agent",
            "locale": "en-GB",
        }

    assert page.closed is True
    assert browser.context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


async def test_browser_manager_closes_resources_after_with_block_exception() -> None:
    """A scraper exception does not prevent browser resource cleanup."""

    manager, page, browser, playwright = make_browser_manager()

    with pytest.raises(RuntimeError, match="scrape failed"):
        async with manager:
            raise RuntimeError("scrape failed")

    assert page.closed is True
    assert browser.context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


def test_browser_manager_page_is_unavailable_before_start() -> None:
    """Accessing the page before startup produces a clear error."""

    manager, _, _, _ = make_browser_manager()

    with pytest.raises(RuntimeError, match="has not been started"):
        _ = manager.page
