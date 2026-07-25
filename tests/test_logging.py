"""Tests for idempotent logging configuration."""

import logging

from app.utils.logging import DATE_FORMAT, LOG_FORMAT, configure_logging


def test_configure_logging_reuses_its_handler() -> None:
    """Repeated configuration does not attach duplicate application handlers."""

    root_logger = logging.getLogger()
    existing_handlers = [
        handler
        for handler in root_logger.handlers
        if getattr(handler, "_dynamic_catalog_monitor_handler", False)
    ]
    for handler in existing_handlers:
        root_logger.removeHandler(handler)

    try:
        logger = configure_logging("debug")
        configure_logging("INFO")
        configured_handlers = [
            handler
            for handler in logger.handlers
            if getattr(handler, "_dynamic_catalog_monitor_handler", False)
        ]

        assert logger.level == logging.INFO
        assert len(configured_handlers) == 1
        assert configured_handlers[0].formatter is not None
        assert configured_handlers[0].formatter._fmt == LOG_FORMAT
        assert configured_handlers[0].formatter.datefmt == DATE_FORMAT
    finally:
        for handler in root_logger.handlers[:]:
            if getattr(handler, "_dynamic_catalog_monitor_handler", False):
                root_logger.removeHandler(handler)
        for handler in existing_handlers:
            root_logger.addHandler(handler)
