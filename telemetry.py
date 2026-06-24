"""Azure Monitor (Application Insights) telemetry wiring.

``configure_telemetry`` is driven purely by the connection string it is given:
a non-empty value enables Azure Monitor; an empty value is a no-op. The decision
lives with configuration, not with any inspection of the runtime environment.

``configure_azure_monitor`` auto-instruments Flask requests, outbound ``requests``
calls, and the Python ``logging`` module, so standard ``logging`` calls and HTTP
spans flow to Application Insights with distributed-trace correlation. It must be
called before the Flask app is created so the Flask instrumentation can wrap it.
"""

from __future__ import annotations

import logging

from azure.monitor.opentelemetry import configure_azure_monitor

logger = logging.getLogger(__name__)

_configured = False


def configure_telemetry(connection_string: str) -> bool:
    """Enable Azure Monitor when a connection string is supplied.

    Returns True when telemetry is on.
    """
    global _configured
    if _configured:
        return True
    if not connection_string:
        return False

    configure_azure_monitor(connection_string=connection_string)
    _configured = True
    logger.info("Azure Monitor telemetry configured.")
    return True
