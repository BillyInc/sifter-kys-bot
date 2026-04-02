"""Shared HTTP session with connection pooling for the KYS backend.

Using a single ``requests.Session`` across modules keeps TCP connections
alive and avoids the overhead of a fresh TLS handshake on every request.

Note: The ``requests`` library is auto-instrumented by OpenTelemetry when
``OTEL_ENABLED=true``.  The ``RequestsInstrumentor`` hooks into
``Session.send()`` so every outbound HTTP call made through this session
automatically gets a child span — no manual wrapping needed here.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_http_session = None


def get_http_session() -> requests.Session:
    """Return a module-level ``requests.Session`` with connection pooling."""
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503])
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=retry)
        _http_session.mount("https://", adapter)
        _http_session.mount("http://", adapter)
    return _http_session
