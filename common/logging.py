"""Shared structured logging for all GroktoCrawl services.

Provides JSONFormatter and setup_logging() — import in each service's app factory
to get consistent JSON-line logging with configurable log levels.
"""

import json
import logging
import os


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter.

    Produces one JSON object per line with fields:
    timestamp, level, logger, message, and optional extra fields.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            log_entry[key] = value
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging(
    default_level: str | None = None,
    quiet_third_party: bool = True,
) -> None:
    """Configure structured JSON logging.

    Replaces the default log format with JSON lines. Sets the root logger
    to the level from ``LOG_LEVEL`` env var (defaults to "INFO").

    Args:
        default_level: Override the env-configured log level.
        quiet_third_party: If True, suppress noisy logs from httpx/httpcore/urllib3.
    """
    log_level = (default_level or os.getenv("LOG_LEVEL", "INFO")).upper()  # type: ignore[union-attr]
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.setLevel(log_level)
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(handler)
    if quiet_third_party:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
