# Dynamic Product Catalog Monitor

A Python 3.12 application for collecting dynamic product catalogs, comparing
snapshots, and exporting reports.

This initial commit provides the project structure and development tooling only.
Scraping, normalization, validation, persistence, comparison, and reporting will
be implemented as separate layers in later commits.

## Setup

Create and activate a Python 3.12 virtual environment, then install the project:

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

Copy `.env.example` to `.env` before configuring a real catalog.

## CLI

Display the available placeholder commands:

```bash
python -m app.main --help
```

## Development checks

```bash
pytest
ruff check .
mypy
```
