"""QR Org Join — multi-org self-service GitHub org joining.

Admins manage a list of GitHub organizations through an Easy Auth-protected CRUD
UI and project a per-org QR code. Participants scan the code, sign in with GitHub
(identity only), and are invited into that org via a per-org GitHub App
installation token (least privilege: *Members: write*). Orgs are stored in Cosmos
DB, accessed passwordlessly via managed identity.

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

import flask
from flask import render_template
from flask_wtf import CSRFProtect

from admin import admin_bp
from auth import auth_bp
from config import Config
from github_client import GitHubClient, PyGithubClient
from participants import participants_bp
from org_store import CosmosOrgStore, OrgStore
from telemetry import configure_telemetry
from webhooks import webhooks_bp

logger = logging.getLogger(__name__)

csrf = CSRFProtect()


def create_app(
    config: Config, org_store: OrgStore, github_client: GitHubClient
) -> flask.Flask:
    """Build the Flask app from injected dependencies.

    Note: the app is created via ``flask.Flask`` (resolved at call time) rather
    than a module-level ``from flask import Flask``. Azure Monitor's Flask
    instrumentation patches the ``flask.Flask`` attribute, so constructing the
    app this way — after ``configure_telemetry`` runs in ``build_app`` — ensures
    incoming requests are captured as Application Insights "requests".
    """
    app = flask.Flask(__name__)
    app.config["APP_CONFIG"] = config
    app.config["ORG_STORE"] = org_store
    app.config["GITHUB"] = github_client
    app.config["SECRET_KEY"] = config.secret_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.cookie_secure,
    )

    # App-wide CSRF protection for every state-changing POST. Tokens are signed
    # with SECRET_KEY and rendered in templates via {{ csrf_token() }}.
    csrf.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(webhooks_bp)
    # The GitHub webhook is a signed server-to-server POST (HMAC-verified), not a
    # browser form — exempt it from CSRF.
    csrf.exempt(webhooks_bp)

    @app.get("/")
    def index():
        # Public landing page — does not require admin sign-in. Admins follow the
        # link to /admin (which triggers Easy Auth); participants reach their org
        # via a QR code at /orgs/<slug>.
        return render_template("index.html")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    return app


# Loggers that must be quieted to WARNING. The Azure SDKs (and especially the
# Azure Monitor exporter) log verbosely at INFO/DEBUG — including the exporter's
# own "Transmission succeeded…" messages and per-request HTTP traces. With Azure
# Monitor's logging instrumentation capturing the root logger, those records are
# themselves exported as telemetry, which makes the exporter log again: a
# self-amplifying feedback loop that floods the export buffer and ingestion,
# causing the *application's* own logs (joins, invites) to be dropped. Silencing
# these breaks the loop so meaningful logs flow reliably.
_NOISY_LOGGERS = (
    "azure",  # parent of azure.core / azure.identity / azure.cosmos / azure.monitor
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.monitor.opentelemetry.exporter",
    "azure.identity",
    "azure.cosmos",
    "urllib3",
    "opentelemetry",
)


def _quiet_noisy_loggers() -> None:
    """Force chatty Azure/HTTP SDK loggers to WARNING (idempotent)."""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _configure_logging(level_name: str) -> None:
    """Send logs to stdout (captured by App Service) at the configured level.

    Application loggers stay at ``level`` (INFO by default); chatty Azure/HTTP
    SDK loggers are forced to WARNING to prevent a telemetry feedback loop that
    would otherwise drown out — and drop — the app's own log records.
    """
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("werkzeug").setLevel(max(level, logging.WARNING))
    _quiet_noisy_loggers()


def build_app() -> flask.Flask:
    """Composition root: construct real dependencies and wire the app."""
    config = Config()

    _configure_logging(config.log_level)
    # Telemetry must be configured before the Flask app is created so its
    # instrumentation can wrap it.
    telemetry_on = configure_telemetry(config.app_insights_connection_string)
    # Re-assert the quiet levels: configure_azure_monitor attaches the logging
    # handler that would otherwise re-export the SDK's own chatty INFO records.
    _quiet_noisy_loggers()

    org_store = CosmosOrgStore(
        endpoint=config.cosmos_endpoint,
        database=config.cosmos_database,
        container=config.cosmos_container,
    )

    github_client = PyGithubClient(
        oauth_client_id=config.github_client_id,
        oauth_client_secret=config.github_client_secret,
        app_id=config.github_app_id,
        app_private_key=config.github_app_private_key,
        redirect_uri=config.github_redirect_uri,
    )

    app = create_app(config, org_store, github_client)
    logger.info("QR Org Join started (telemetry=%s)", "on" if telemetry_on else "off")
    return app


# WSGI entry point for `gunicorn app:app`.
app = build_app()
