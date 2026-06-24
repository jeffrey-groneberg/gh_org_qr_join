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

import os

from flask import Flask, redirect, url_for

from admin import admin_bp
from auth import auth_bp
from config import Config
from extensions import db
from participants import participants_bp


def create_app() -> Flask:
    config = Config()

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

    with app.app_context():
        db.create_all()

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
