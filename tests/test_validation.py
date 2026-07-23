"""Scaffold checks for the validation layer."""


def test_validation_module_is_importable() -> None:
    """The validation layer is available for later implementation."""
    from app.services import validation

    assert validation.__doc__
