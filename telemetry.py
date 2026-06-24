"""Azure Monitor (Application Insights) telemetry wiring.

Telemetry is enabled only when ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set
(i.e. on Azure, where Terraform injects it). Locally, or if the SDK is missing,
this is a safe no-op so the app runs unchanged.

``configure_azure_monitor`` auto-instruments Flask requests, outbound ``requests``
calls, and the Python ``logging`` module, so standard ``logging`` calls and HTTP
spans flow to Application Insights with distributed-trace correlation.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_configured = False


def configure_telemetry() -> bool:
    """Enable Azure Monitor if configured. Returns True when telemetry is on.

    Must be called before the Flask app is created so the Flask instrumentation
    can wrap it.
    """
    global _configured
    if _configured:
        return True

    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        return False

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is set but "
            "azure-monitor-opentelemetry is not installed; telemetry disabled."
        )
        return False

    configure_azure_monitor(connection_string=connection_string)
    _configured = True
    logger.info("Azure Monitor telemetry configured.")
    return True
