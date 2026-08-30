"""Privacy-safe structured logging helpers."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


def configure_logging() -> None:
    formatter = logging.Formatter("%(message)s")
    for name in ("amex_reminders.http", "amex_reminders.lifecycle", "amex_reminders.delivery"):
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))
