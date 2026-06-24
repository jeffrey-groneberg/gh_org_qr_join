"""QR Org Join — multi-org self-service GitHub org joining.

Admins manage a list of GitHub organizations through an Easy Auth-protected CRUD
UI and project a per-org QR code. Participants scan the code, sign in with GitHub
(identity only), and are invited into that org via a single classic PAT. Orgs are
stored in Cosmos DB, accessed passwordlessly via managed identity.

This module separates two concerns:

  * ``create_app(config, org_store)`` — a *pure factory* that wires a Flask app
    from its injected dependencies. It knows nothing about the environment or
    about testing; tests call it directly with their own ``OrgStore``.
  * the module-level ``app`` — the *composition root* that constructs the real
    configuration, telemetry, and Cosmos-backed store, then builds the app. This
    is what ``gunicorn app:app`` imports.
"""

from __future__ import annotations

import logging

from flask import Flask, redirect, url_for

from admin import admin_bp
from auth import auth_bp
from config import Config
from participants import participants_bp
from repository import CosmosOrgStore, OrgStore
from telemetry import configure_telemetry

logger = logging.getLogger(__name__)


def create_app(config: Config, org_store: OrgStore) -> Flask:
    """Build the Flask app from injected dependencies."""
    app = Flask(__name__)
    app.config["APP_CONFIG"] = config
    app.config["ORG_STORE"] = org_store
    app.config["SECRET_KEY"] = config.secret_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.cookie_secure,
    )

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(participants_bp)

    @app.get("/")
    def index():
        return redirect(url_for("admin.list_orgs"))

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    return app


def _configure_logging(level_name: str) -> None:
    """Send logs to stdout (captured by App Service) at the configured level."""
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("werkzeug").setLevel(max(level, logging.WARNING))


def build_app() -> Flask:
    """Composition root: construct real dependencies and wire the app."""
    config = Config()

    _configure_logging(config.log_level)
    # Telemetry must be configured before the Flask app is created so its
    # instrumentation can wrap it.
    telemetry_on = configure_telemetry(config.app_insights_connection_string)

    org_store = CosmosOrgStore(
        endpoint=config.cosmos_endpoint,
        database=config.cosmos_database,
        container=config.cosmos_container,
    )

    app = create_app(config, org_store)
    logger.info("QR Org Join started (telemetry=%s)", "on" if telemetry_on else "off")
    return app


# WSGI entry point for `gunicorn app:app` and `python app.py`.
app = build_app()


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
