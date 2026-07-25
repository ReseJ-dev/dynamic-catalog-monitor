"""Tests for failure diagnostic artifact creation."""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.utils.diagnostics import save_failure_diagnostics

TIMESTAMP = datetime(2026, 7, 25, 14, 5, 6, tzinfo=UTC)


class FakeDiagnosticPage:
    """A page fake that can save a screenshot and return HTML."""

    def __init__(self, *, screenshot_fails: bool = False, content_fails: bool = False) -> None:
        self.url = "https://example.test/catalog"
        self.screenshot_fails = screenshot_fails
        self.content_fails = content_fails

    async def screenshot(self, *, path: str) -> None:
        """Write a minimal fake image or simulate a capture error."""

        if self.screenshot_fails:
            raise RuntimeError("screenshot unavailable")
        Path(path).write_bytes(b"fake-png")

    async def content(self) -> str:
        """Return test HTML or simulate a content error."""

        if self.content_fails:
            raise RuntimeError("content unavailable")
        return "<html><body>fixture</body></html>"


async def test_save_failure_diagnostics_creates_expected_artifacts(tmp_path: Path) -> None:
    """A page failure produces screenshot, HTML, and structured JSON artifacts."""

    exception = ValueError("invalid product price")
    artifacts = await save_failure_diagnostics(
        FakeDiagnosticPage(),
        exception,
        diagnostics_dir=tmp_path / "diagnostics",
        stage="normalize_product",
        products_collected=3,
        run_id=42,
        timestamp=TIMESTAMP,
    )

    assert artifacts.screenshot_path is not None
    assert artifacts.html_path is not None
    assert artifacts.metadata_path is not None
    assert artifacts.screenshot_path.name == "error_2026-07-25_140506.png"
    assert artifacts.html_path.read_text(encoding="utf-8") == "<html><body>fixture</body></html>"
    metadata = json.loads(artifacts.metadata_path.read_text(encoding="utf-8"))
    assert metadata["timestamp"] == "2026-07-25T14:05:06+00:00"
    assert metadata["current_url"] == "https://example.test/catalog"
    assert metadata["exception_type"] == "ValueError"
    assert metadata["exception_message"] == "invalid product price"
    assert "ValueError: invalid product price" in metadata["traceback"]
    assert metadata["stage"] == "normalize_product"
    assert metadata["products_collected"] == 3
    assert metadata["run_id"] == 42


async def test_diagnostic_capture_failure_does_not_raise_or_hide_metadata(tmp_path: Path) -> None:
    """A screenshot or HTML failure cannot replace the original scraper error."""

    artifacts = await save_failure_diagnostics(
        FakeDiagnosticPage(screenshot_fails=True, content_fails=True),
        RuntimeError("catalog request failed"),
        diagnostics_dir=tmp_path / "diagnostics",
        stage="load_more",
        products_collected=7,
        save_screenshot=True,
        timestamp=TIMESTAMP,
    )

    assert artifacts.screenshot_path is None
    assert artifacts.html_path is None
    assert artifacts.metadata_path is not None
    metadata = json.loads(artifacts.metadata_path.read_text(encoding="utf-8"))
    assert metadata["exception_message"] == "catalog request failed"
    assert metadata["stage"] == "load_more"
