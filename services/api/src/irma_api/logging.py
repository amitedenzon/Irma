"""Structured logging via ``structlog``.

JSON on stderr in non-TTY environments (containers, CI, launchd) — key/value
console renderer for interactive sessions.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    """Configure stdlib + structlog. Idempotent."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    pre_chain: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
    ]

    interactive = sys.stderr.isatty()
    renderer: structlog.types.Processor
    if interactive:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *pre_chain,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        level=level,
        handlers=[logging.StreamHandler(sys.stderr)],
        force=True,
    )
    # Mute noisy library access logs unless explicitly turned up.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
