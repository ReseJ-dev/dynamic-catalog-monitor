"""Typer CLI tests with mocked asynchronous services."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from app import main
from app.models import ComparisonResult, RunSummary
from app.services.orchestration import CatalogRunResult, ComparisonSummary

runner = CliRunner()


def completed_run_result(report_path: Path) -> CatalogRunResult:
    """Build a successful scrape result for CLI command tests."""

    comparison = ComparisonResult()
    return CatalogRunResult(
        run_id=42,
        status="completed",
        counters=RunSummary(total_scraped=3, valid_products=2, invalid_records=1),
        report_path=report_path,
        comparison=comparison,
        comparison_summary=ComparisonSummary(0, 0, 0, 0, 0),
    )


def test_scrape_applies_options_and_prints_report_path(monkeypatch: object, tmp_path: Path) -> None:
    """The scrape command forwards CLI overrides and prints a concise outcome."""

    captured: dict[str, object] = {}

    async def fake_run_scrape(settings: object) -> CatalogRunResult:
        """Capture settings without starting a real browser."""

        captured["settings"] = settings
        return completed_run_result(tmp_path / "report.xlsx")

    monkeypatch.setattr(main, "_run_scrape", fake_run_scrape)  # type: ignore[attr-defined]

    result = runner.invoke(
        main.app,
        [
            "scrape",
            "--headful",
            "--max-items",
            "100",
            "--catalog-url",
            "https://shop.example.test/catalog",
            "--output-dir",
            str(tmp_path),
        ],
    )

    settings = captured["settings"]
    assert result.exit_code == 0
    assert "Scrape completed" in result.stdout
    assert "report.xlsx" in result.stdout
    assert settings.headless is False  # type: ignore[attr-defined]
    assert settings.max_items == 100  # type: ignore[attr-defined]
    assert str(settings.catalog_url) == "https://shop.example.test/catalog"  # type: ignore[attr-defined]
    assert settings.output_dir == tmp_path  # type: ignore[attr-defined]


def test_scrape_returns_nonzero_status_for_failed_result(
    monkeypatch: object, tmp_path: Path
) -> None:
    """A structured failed workflow result maps to a controlled CLI exit code."""

    async def fake_run_scrape(_settings: object) -> CatalogRunResult:
        """Return a failure result without starting infrastructure."""

        comparison = ComparisonResult()
        return CatalogRunResult(
            run_id=42,
            status="failed",
            counters=RunSummary(),
            report_path=None,
            comparison=comparison,
            comparison_summary=ComparisonSummary(0, 0, 0, 0, 0),
        )

    monkeypatch.setattr(main, "_run_scrape", fake_run_scrape)  # type: ignore[attr-defined]

    result = runner.invoke(main.app, ["scrape", "--output-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "failed" in result.output


def test_compare_prints_counts_and_handles_missing_baseline(monkeypatch: object) -> None:
    """Compare prints counts on success and exits cleanly when two runs do not exist."""

    async def fake_compare(
        _settings: object,
        *,
        export_report: bool,
    ) -> main.SnapshotCommandResult:
        """Return a comparison result without reading SQLite."""

        assert export_report is False
        return main.SnapshotCommandResult(ComparisonResult(), None)

    monkeypatch.setattr(main, "_run_compare", fake_compare)  # type: ignore[attr-defined]

    result = runner.invoke(main.app, ["compare"])

    assert result.exit_code == 0
    assert "New products: 0" in result.stdout

    async def no_baseline(
        _settings: object,
        *,
        export_report: bool,
    ) -> None:
        """Model the fewer-than-two-runs condition."""

        del export_report
        return None

    monkeypatch.setattr(main, "_run_compare", no_baseline)  # type: ignore[attr-defined]
    missing_result = runner.invoke(main.app, ["compare"])

    assert missing_result.exit_code == 1
    assert "two completed runs" in missing_result.output


def test_export_prints_generated_report_path(monkeypatch: object, tmp_path: Path) -> None:
    """Export displays its regenerated report path without scraping."""

    async def fake_export(
        _settings: object,
        *,
        destination: Path | None,
    ) -> main.SnapshotCommandResult:
        """Return a report result without using persistence or Excel."""

        assert destination == tmp_path
        return main.SnapshotCommandResult(ComparisonResult(), tmp_path / "export.xlsx")

    monkeypatch.setattr(main, "_run_export", fake_export)  # type: ignore[attr-defined]

    result = runner.invoke(main.app, ["export", "--destination", str(tmp_path)])

    assert result.exit_code == 0
    assert "export.xlsx" in result.stdout
