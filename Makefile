.PHONY: test test-integration coverage lint format-check typecheck quality

test:
	python -m pytest

test-integration:
	python -m pytest -m integration

coverage:
	python -m pytest --cov=app

lint:
	python -m ruff check .

format-check:
	python -m ruff format --check .

typecheck:
	python -m mypy app

quality: test lint format-check typecheck
