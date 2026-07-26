"""Tests for immutable scraper selector groups."""

from dataclasses import FrozenInstanceError

import pytest

from app.scraper.selectors import (
    CatalogSelectors,
    DetailPageSelectors,
    scraping_sandbox_catalog_selectors,
)


def test_catalog_selectors_have_expected_defaults() -> None:
    """Catalog selector defaults match the initial target markup."""

    selectors = CatalogSelectors()

    assert selectors.product_card == "article.product-card"
    assert selectors.product_title == ".product-title"
    assert selectors.product_price == ".product-price"
    assert selectors.product_link == "a.product-link"
    assert selectors.load_more_button == "button[data-testid='load-more']"


def test_selector_groups_are_immutable() -> None:
    """Selector configuration cannot change during a scraping run."""

    selectors = DetailPageSelectors()

    with pytest.raises(FrozenInstanceError):
        selectors.title = ".replacement-title"  # type: ignore[misc]


def test_scraping_sandbox_selectors_match_its_product_card_markup() -> None:
    """The public practice catalog profile targets stable semantic CSS classes."""

    selectors = scraping_sandbox_catalog_selectors()

    assert selectors.product_card == "a.product-card"
    assert selectors.product_id == ".sku"
    assert selectors.product_title == ".product-name"
    assert selectors.product_link == "a.product-link-not-present"
