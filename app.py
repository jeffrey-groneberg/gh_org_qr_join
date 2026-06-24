"""QR Org Join — multi-org self-service GitHub org joining.

Admins manage a list of GitHub organizations through an Easy Auth-protected CRUD
UI and project a per-org QR code. Participants scan the code, sign in with GitHub
(identity only), and are invited into that org via a single classic PAT. The app
never administers members itself — joining/accepting happens on GitHub.

Three credentials, each at minimum privilege:
  - Entra ID app role (via App Service Easy Auth) -> authorizes the admin.
  - GitHub OAuth App -> identifies the participant (no scopes).
  - GitHub classic PAT (admin:org) -> creates the invitation.

WSGI entrypoint: ``gunicorn app:app``  (or ``python app.py`` for local dev).
"""

from __future__ import annotations

import logging
import os

from flask import Flask, redirect, url_for
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import OperationalError

from admin import admin_bp
from auth import auth_bp
from config import Config
from extensions import db
from participants import participants_bp
from telemetry import configure_telemetry

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Send logs to stdout (captured by App Service) at the configured level."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Quiet noisy access logs from the dev server unless explicitly debugging.
    logging.getLogger("werkzeug").setLevel(max(level, logging.WARNING))


def _init_schema() -> None:
    """Create tables idempotently, tolerating concurrent gunicorn workers.

    Each worker runs the app factory, so several may call ``create_all`` at once
    on the shared SQLite file. ``create_all`` checks-then-creates, so a race can
    surface as "table already exists" — safe to ignore once the schema is there.
    """
    try:
        db.create_all()
    except OperationalError:
        if not sa_inspect(db.engine).has_table("orgs"):
            raise
        logger.info("Schema already present (created by a concurrent worker).")


def create_app() -> Flask:
    config = Config()

    # Logging first, then telemetry (which attaches its handler to the root
    # logger and must run before the Flask app is created to instrument it).
    _configure_logging()
    telemetry_on = configure_telemetry()

    app = Flask(__name__)
    app.config["APP_CONFIG"] = config
    app.config["SECRET_KEY"] = config.secret_key
    app.config["SQLALCHEMY_DATABASE_URI"] = config.database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.cookie_secure,
    )

    db.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(participants_bp)

    config.ensure_sqlite_dir()
    with app.app_context():
        _init_schema()

    logger.info(
        "QR Org Join started (telemetry=%s, db=%s)",
        "on" if telemetry_on else "off",
        config.database_url.split("://", 1)[0],
    )

    @app.get("/")
    def index():
        return redirect(url_for("admin.list_orgs"))

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
