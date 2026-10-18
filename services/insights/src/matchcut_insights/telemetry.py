"""Tracing to Azure Application Insights with OpenTelemetry (Microsoft's documented pattern).

Off unless ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set, so tests and local runs
send nothing. When on, every workflow executor, agent run, model call (with token
counts) and MCP tool call becomes a span. Message content is never recorded
(sensitive data stays off).
"""

from __future__ import annotations

import os

from agent_framework.observability import enable_instrumentation
from azure.monitor.opentelemetry import configure_azure_monitor

_configured = False


def configure_telemetry(service_name: str) -> bool:
    """Configure once per process; return True when telemetry is being exported."""
    global _configured  # noqa: PLW0603 - one provider per process, by OpenTelemetry design
    if _configured or not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return _configured
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    configure_azure_monitor()  # reads the connection string; adds HTTP and FastAPI instrumentation
    enable_instrumentation(enable_sensitive_data=False)
    _configured = True
    return True
