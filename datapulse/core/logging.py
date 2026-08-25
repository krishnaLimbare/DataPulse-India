"""Structured logging.

Human-readable in a terminal, JSON when running in CI so logs stay greppable.
Never log secrets: use `redact()` for anything that may carry credentials.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any

_SECRET_HINTS = ("key", "token", "secret", "password", "auth", "cookie")

# Credentials passed as query parameters leak through exception messages,
# which end up in committed run reports. Scrub anything that looks like one.
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:api[-_]?key|key|token|access[-_]?token|secret|password|auth|sig)=)[^&\s'\"]+"
)


def scrub(text: str) -> str:
    """Mask credentials embedded in URLs inside an arbitrary string."""
    return _QUERY_SECRET.sub(r"\1***redacted***", text)


def redact(value: Any, key: str = "") -> Any:
    """Mask values whose key looks credential-ish, recursively for dicts."""
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if any(h in key.lower() for h in _SECRET_HINTS) and value:
        return "***redacted***"
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": scrub(record.getMessage()),
        }
        extra = getattr(record, "context", None)
        if extra:
            payload["context"] = redact(extra)
        if record.exc_info:
            payload["exc"] = scrub(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", json_logs: bool | None = None) -> None:
    if json_logs is None:
        json_logs = os.getenv("CI", "").lower() == "true"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if json_logs
        else logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
