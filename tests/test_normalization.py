"""Scaffold checks for the normalization layer."""


def test_normalization_module_is_importable() -> None:
    """The normalization layer is available for later implementation."""
    from app.services import normalization

    assert normalization.__doc__
