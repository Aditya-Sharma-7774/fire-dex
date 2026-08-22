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
import sys

import structlog


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

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
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
