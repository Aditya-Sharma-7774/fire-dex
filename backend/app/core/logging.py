"""Structured logging setup.

Why structlog instead of plain `logging`?

Later, Fire Auditor needs machine-readable records of every agent run:
duration, token counts, status, errors. If logs are formatted strings we
would have to parse them back out. With structlog every log line is a dict
from the start, so the same call site serves both humans and the auditor.

    log.info("agent_completed", agent="market", duration_ms=812)

Locally that prints a readable coloured line. With LOG_JSON=true it prints
one JSON object per line.
"""

import logging
import re
import sys
from typing import Any

import structlog

# Shapes of secret that could reach a log or an error response. A user who
# pastes a key into the wrong field must not see it repeated on screen or
# kept in a log, and an API key embedded in an RPC URL must not leak through
# a connection error.
_SECRETS = [
    (re.compile(r"\bgsk_[A-Za-z0-9]{16,}"), "gsk_[redacted]"),
    # An EVM private key: exactly 64 hex characters. An address is 40, so
    # addresses are untouched.
    (re.compile(r"\b(?:0x)?[0-9a-fA-F]{64}\b"), "[redacted 64-hex]"),
    # A Solana secret key: 64 bytes base58-encode to roughly 88 characters.
    # A public address is at most 44, so addresses are untouched.
    (re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{80,}\b"), "[redacted secret]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [redacted]"),
    # Keep the host, drop the path and query, which is where providers such
    # as Alchemy put the API key.
    (re.compile(r"(https?://[^/\s?#]+)[/?#][^\s\"')]*"), r"\1/[...]"),
]


def redact(text: str) -> str:
    """Remove anything shaped like a secret."""
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(item) for item in value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    return value


def _redact_event(_logger: Any, _method: str, event: dict) -> dict:
    """structlog processor: applied to every project log line, in one place."""
    return {key: _redact_value(value) for key, value in event.items()}


class RedactingFilter(logging.Filter):
    """Redacts records from libraries that log through the standard library.

    Needed for the server's access log in particular, which records the full
    request path -- including any address segment -- before project code runs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = _redact_value(record.args)
        return True


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure structlog and the stdlib logging bridge.

    Call once, at application startup, before anything logs.

    Args:
        level: Standard level name, e.g. "DEBUG", "INFO", "WARNING".
        json_output: True for one-JSON-object-per-line (production/parsing),
            False for coloured human-readable output (local development).
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Route stdlib logging (uvicorn, httpx, sqlalchemy) through the same handler
    # so we do not end up with two different log formats interleaved.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )
    for name in ("uvicorn.access", "uvicorn.error", "httpx"):
        logging.getLogger(name).addFilter(RedactingFilter())

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _redact_event,
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
        shared_processors.append(structlog.processors.format_exc_info)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a logger bound to a module name.

    Usage:
        log = get_logger(__name__)
        log.info("something_happened", key="value")
    """
    return structlog.get_logger(name)
