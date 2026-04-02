"""
OpenTelemetry initialization for the KYS backend.

Opt-in: set ``OTEL_ENABLED=true`` to activate tracing.
When disabled (default), all helpers return no-op objects so callers
never need to guard against ``None``.
"""

import os
import logging

from opentelemetry import trace

logger = logging.getLogger(__name__)

_initialised = False

SERVICE_NAME = "sifter-kys-backend"


def _is_enabled() -> bool:
    return os.environ.get("OTEL_ENABLED", "false").lower() in ("true", "1", "yes")


def init_telemetry() -> None:
    """Configure the OTel TracerProvider and auto-instrument libraries.

    Safe to call multiple times; only the first call has an effect.
    When ``OTEL_ENABLED`` is falsy the function returns immediately,
    leaving the global no-op tracer in place.
    """
    global _initialised
    if _initialised:
        return
    _initialised = True

    if not _is_enabled():
        logger.info("[OTEL] Telemetry disabled (set OTEL_ENABLED=true to enable)")
        return

    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME as RES_SVC
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        endpoint = os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
        )

        resource = Resource.create({RES_SVC: SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # --- Auto-instrumentation ---
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        FlaskInstrumentor().instrument()
        RequestsInstrumentor().instrument()
        RedisInstrumentor().instrument()
        CeleryInstrumentor().instrument()
        LoggingInstrumentor().instrument(set_logging_format=False)

        logger.info(
            "[OTEL] Telemetry enabled — exporting to %s", endpoint
        )
    except Exception:
        logger.exception("[OTEL] Failed to initialise telemetry; continuing without it")


def get_tracer(name: str = SERVICE_NAME) -> trace.Tracer:
    """Return a tracer scoped to *name*.

    Always safe to call regardless of whether telemetry is enabled;
    returns the global (possibly no-op) tracer provider's tracer.
    """
    return trace.get_tracer(name)
