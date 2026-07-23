"""Scaffold checks for the reporting layer."""


def test_reporting_module_is_importable() -> None:
    """The reporting layer is available for later implementation."""
    from app.services import reporting

    assert reporting.__doc__
