"""Scaffold checks for the deduplication layer."""


def test_deduplication_module_is_importable() -> None:
    """The deduplication layer is available for later implementation."""
    from app.services import deduplication

    assert deduplication.__doc__
