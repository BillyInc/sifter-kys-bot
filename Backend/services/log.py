"""
Structured logging configuration for the KYS backend.
Usage: from services.log import get_logger
       logger = get_logger(__name__)
       logger.info("event_name", key="value")
"""
import logging
import logging.handlers
import os
import sys

import structlog
from opentelemetry import trace


def _add_otel_context(logger, method_name, event_dict):
    """Inject trace_id and span_id from the current OTel span into every log line."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.trace_id:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def setup_logging(log_level: str = "INFO"):
    """Configure structlog with JSON output for production, pretty for dev."""

    root = logging.getLogger()

    # Guard against double-init
    if root.handlers:
        return

    # Create logs directory
    os.makedirs("logs", exist_ok=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_otel_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(),  # Pretty for dev; swap to JSONRenderer() for prod
        ],
    )

    file_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Rotating file handler — general log (10MB, 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        "logs/sifter.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(file_formatter)

    # Rotating file handler — errors only (5MB, 3 backups)
    error_handler = logging.handlers.RotatingFileHandler(
        "logs/errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)

    root.addHandler(console_handler)
    root.addHandler(file_handler)
    root.addHandler(error_handler)
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Suppress noisy loggers
    for noisy in ("urllib3", "httpx", "celery", "kombu"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str):
    """Get a structlog logger bound to a module name."""
    return structlog.get_logger(name)
