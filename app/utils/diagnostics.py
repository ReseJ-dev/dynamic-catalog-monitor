"""Failure diagnostics for catalog scraping."""

import asyncio
import json
import logging
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

LOGGER = logging.getLogger(__name__)


class DiagnosticPage(Protocol):
    """The small subset of a Playwright page required for diagnostics."""

    @property
    def url(self) -> str:
        """Return the page's current URL."""

    async def screenshot(self, *, path: str) -> object:
        """Save a screenshot to a path."""

    async def content(self) -> str:
        """Return the current document HTML."""


@dataclass(frozen=True)
class DiagnosticArtifacts:
    """Paths to diagnostics that were saved successfully."""

    screenshot_path: Path | None
    html_path: Path | None
    metadata_path: Path | None


async def save_failure_diagnostics(
    page: DiagnosticPage | None,
    exception: BaseException,
    *,
    diagnostics_dir: Path,
    stage: str,
    products_collected: int,
    run_id: int | None = None,
    save_screenshot: bool = True,
    timestamp: datetime | None = None,
) -> DiagnosticArtifacts:
    """Save available page artifacts and metadata without raising a new error."""

    captured_at = timestamp or datetime.now(UTC)
    filename_timestamp = captured_at.strftime("%Y-%m-%d_%H%M%S")
    screenshot_path = diagnostics_dir / f"error_{filename_timestamp}.png"
    html_path = diagnostics_dir / f"error_{filename_timestamp}.html"
    metadata_path = diagnostics_dir / f"error_{filename_timestamp}.json"

    try:
        await asyncio.to_thread(diagnostics_dir.mkdir, parents=True, exist_ok=True)
    except Exception:
        LOGGER.exception("Unable to create diagnostics directory: %s", diagnostics_dir)
        return DiagnosticArtifacts(None, None, None)

    current_url = _current_url(page)
    saved_screenshot = None
    saved_html = None
    saved_metadata = None

    if page is not None and save_screenshot:
        try:
            await page.screenshot(path=str(screenshot_path))
            saved_screenshot = screenshot_path
        except Exception:
            LOGGER.exception("Unable to save failure screenshot")

    if page is not None:
        try:
            html = await page.content()
            await asyncio.to_thread(html_path.write_text, html, encoding="utf-8")
            saved_html = html_path
        except Exception:
            LOGGER.exception("Unable to save failure HTML")

    metadata = {
        "timestamp": captured_at.isoformat(),
        "current_url": current_url,
        "exception_type": type(exception).__name__,
        "exception_message": str(exception),
        "traceback": "".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        ),
        "stage": stage,
        "products_collected": products_collected,
        "run_id": run_id,
    }
    try:
        content = json.dumps(metadata, ensure_ascii=False, indent=2)
        await asyncio.to_thread(metadata_path.write_text, content, encoding="utf-8")
        saved_metadata = metadata_path
    except Exception:
        LOGGER.exception("Unable to save failure metadata")

    return DiagnosticArtifacts(saved_screenshot, saved_html, saved_metadata)


def _current_url(page: DiagnosticPage | None) -> str | None:
    """Read a page URL without letting a broken page mask the original failure."""

    if page is None:
        return None
    try:
        return page.url
    except Exception:
        LOGGER.exception("Unable to read failure page URL")
        return None
