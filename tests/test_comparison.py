"""Scaffold checks for the comparison layer."""


def test_comparison_module_is_importable() -> None:
    """The comparison layer is available for later implementation."""
    from app.services import comparison

    assert comparison.__doc__
