"""Application logging configuration."""

import logging

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_HANDLER_MARKER = "_dynamic_catalog_monitor_handler"


def configure_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure the root logger once and return it."""

    normalized_level = log_level.upper()
    level = logging.getLevelNamesMapping().get(normalized_level)
    if level is None:
        raise ValueError(f"unknown log level: {log_level}")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not any(getattr(handler, _HANDLER_MARKER, False) for handler in root_logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        setattr(handler, _HANDLER_MARKER, True)
        root_logger.addHandler(handler)
    return root_logger
