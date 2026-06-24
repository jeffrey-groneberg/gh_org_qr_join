"""Application configuration loaded once from the environment.

Identity is split across two independent systems:

  * **App Service Easy Auth** (Entra ID) authenticates the *admin* before the
    request reaches Flask and injects their claims as request headers. The app
    only needs to know which Entra **app role** grants admin access — it never
    holds an Entra client secret. Easy Auth is configured to allow
    unauthenticated requests so participants pass through untouched.
  * **GitHub OAuth App** identifies the *participant* (empty scope) so we learn
    their login before inviting them.

A single classic PAT (``admin:org``) performs every org invitation, so no
per-org secret is ever stored in the database.
"""

from __future__ import annotations

import os

from sqlalchemy.engine import make_url


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

        # --- Database --------------------------------------------------------
        # On Azure App Service put the file under /home (persistent), e.g.
        #   sqlite:////home/data/qr_org_join.db
        self.database_url = (
            os.environ.get("DATABASE_URL", "").strip() or "sqlite:///qr_org_join.db"
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

    def ensure_sqlite_dir(self) -> None:
        """Create the parent directory for a file-backed SQLite database.

        On Azure App Service the DB lives at /home/data/... which persists, but
        the directory does not exist on a fresh app — SQLite creates the file,
        not its parent — so the first write would fail without this.
        """
        url = make_url(self.database_url)
        if url.get_backend_name() != "sqlite":
            return
        if not url.database or url.database == ":memory:":
            return
        directory = os.path.dirname(url.database)
        if directory:
            os.makedirs(directory, exist_ok=True)
