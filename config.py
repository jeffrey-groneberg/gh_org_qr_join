"""Application configuration loaded once from the environment.

Identity is split across two independent systems:

  * **App Service Easy Auth** (Entra ID) authenticates the *admin* before the
    request reaches Flask and injects their claims as request headers. The app
    only needs to know which Entra **app role** grants admin access — it never
    holds an Entra client secret. Easy Auth is configured to allow
    unauthenticated requests so participants pass through untouched.
  * **GitHub OAuth App** identifies the *participant* (empty scope) so we learn
    their login before inviting them.

A single classic PAT (``admin:org``) performs every org invitation, and orgs are
stored in Cosmos DB accessed via managed identity, so no data-store or per-org
secret is ever held by the app.

This module is the single place that reads ``os.environ``; everything else
depends on a ``Config`` instance.
"""

from __future__ import annotations

import os


def _require_env(name: str) -> str:
    """Return a required environment variable or raise a clear startup error."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "See .env.example for the full list."
        )
    return value


def _bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Application configuration loaded once from the environment."""

    def __init__(self) -> None:
        # --- Flask session ---------------------------------------------------
        self.secret_key = _require_env("FLASK_SECRET_KEY")

        # --- Public base URL -------------------------------------------------
        # Encoded in the QR targets and used to build the GitHub redirect URI.
        # Set explicitly so everything stays deterministic regardless of
        # proxy/tunnel/container.
        self.base_url = _require_env("APP_BASE_URL").rstrip("/")
        self.cookie_secure = self.base_url.lower().startswith("https://")

        # --- Cosmos DB (orgs store; passwordless via managed identity) -------
        self.cosmos_endpoint = _require_env("COSMOS_ENDPOINT")
        self.cosmos_database = (
            os.environ.get("COSMOS_DATABASE", "qrorgjoin").strip() or "qrorgjoin"
        )
        self.cosmos_container = (
            os.environ.get("COSMOS_CONTAINER", "orgs").strip() or "orgs"
        )

        # --- GitHub OAuth App (participant identity, empty scope) ------------
        self.github_client_id = _require_env("GITHUB_CLIENT_ID")
        self.github_client_secret = _require_env("GITHUB_CLIENT_SECRET")

        # --- GitHub classic PAT (admin:org) used for every invitation -------
        self.invite_token = _require_env("GITHUB_INVITE_TOKEN")

        # --- Admin authorization (via Easy Auth app role) -------------------
        # The Entra app role that grants admin access (case-insensitive match).
        self.entra_admin_role = (
            os.environ.get("ENTRA_ADMIN_ROLE", "admin").strip() or "admin"
        )
        # Local-dev escape hatch: treat the local user as an admin when there is
        # no Easy Auth in front of the app. Never enable in production.
        self.admin_dev_bypass = _bool_env("ADMIN_DEV_BYPASS")

        # --- Observability ---------------------------------------------------
        self.log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        # An empty value disables telemetry — the configuration value drives the
        # decision, not any inspection of the runtime environment.
        self.app_insights_connection_string = os.environ.get(
            "APPLICATIONINSIGHTS_CONNECTION_STRING", ""
        ).strip()

        # --- Defaults --------------------------------------------------------
        # Default role applied to a new org if the admin doesn't pick one.
        self.default_member_role = (
            os.environ.get("MEMBER_ROLE", "member").strip() or "member"
        )
        if self.default_member_role not in {"member", "admin"}:
            raise RuntimeError("MEMBER_ROLE must be 'member' or 'admin'.")

    # --- Derived URLs --------------------------------------------------------
    @property
    def github_redirect_uri(self) -> str:
        return f"{self.base_url}/callback"

    def org_join_url(self, slug: str) -> str:
        """Public URL a participant lands on (encoded in the org's QR code)."""
        return f"{self.base_url}/orgs/{slug}"
