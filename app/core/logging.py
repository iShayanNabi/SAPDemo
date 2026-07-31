"""Central logging configuration.

All modules obtain their logger via :func:`get_logger` so that formatting,
levels and secret redaction are configured in exactly one place.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Final

from app.core.config import settings

_CONFIGURED = False

# Patterns that must never reach a log file or the console.
_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*)([^\s,;\"']+)"),
)

_PLAIN_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_JSON_FORMAT = (
    '{"time":"%(asctime)s","level":"%(levelname)s",'
    '"logger":"%(name)s","message":"%(message)s"}'
)


class SecretRedactingFilter(logging.Filter):
    """Replace anything that looks like an API key with ``***REDACTED***``."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        message = record.getMessage()
        redacted = message
        for pattern in _SECRET_PATTERNS:
            if pattern.groups >= 2:
                redacted = pattern.sub(r"\1***REDACTED***", redacted)
            else:
                redacted = pattern.sub("***REDACTED***", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging() -> None:
    """Configure the root logger once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(_JSON_FORMAT if settings.log_json else _PLAIN_FORMAT))
    handler.addFilter(SecretRedactingFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Third party libraries are noisy at DEBUG level.
    for noisy in ("httpx", "httpcore", "urllib3", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for ``name``."""
    configure_logging()
    return logging.getLogger(name)
