"""GitHub access for the app, built entirely on **PyGithub** (one SDK, no mixing).

Two independent GitHub integrations live behind a single injected interface:

* **OAuth App** — identifies a *participant* (empty scope). Used to turn an OAuth
  ``code`` into the user's login. Backed by PyGithub's ``ApplicationOAuth``.
* **GitHub App** — sends org **invitations** with least privilege
  (*Members: write*), per-org, via short-lived **installation** tokens, and
  best-effort assigns a **Copilot** seat to the invitee (needs the org's
  *GitHub Copilot Business* permission). Backed by PyGithub's ``Auth.AppAuth`` →
  ``GithubIntegration`` → ``AppInstallationAuth`` (PyGithub mints and
  auto-refreshes the ~1 h installation token).

``GitHubClient`` is the abstraction the Flask blueprints depend on; the app is
wired with a concrete ``PyGithubClient`` from the composition root, so route
handlers never touch PyGithub directly and tests can inject a fake.
"""

from __future__ import annotations

import logging
import threading
from typing import NamedTuple, Protocol, runtime_checkable

from github import Auth, Github, GithubIntegration
from github.GithubException import (
    GithubException,
    RateLimitExceededException,
    UnknownObjectException,
)

logger = logging.getLogger(__name__)

# Invitations API role for a normal member (POST /orgs/{org}/invitations).
_MEMBER_ROLE = "direct_member"


class OrgStatus(NamedTuple):
    """Result of validating an org for the admin UI."""

    status: str  # "ok" | "not_installed" | "missing" | "error"
    detail: str


class InviteResult(NamedTuple):
    """Outcome of an invitation attempt, mapped to participant-facing state."""

    outcome: str  # "invited" | "already_member" | "not_installed" | "rate_limited" | "error"
    state: str = ""  # "pending" | "active" | ""
    copilot: str = ""  # "assigned" | "" — best-effort Copilot seat outcome


@runtime_checkable
class GitHubClient(Protocol):
    """The GitHub interface the application depends on."""

    # --- Participant identity (OAuth App) ---
    def oauth_login_url(self, state: str) -> str: ...

    def exchange_code_for_login(self, code: str, state: str) -> str | None: ...

    # --- Org membership (GitHub App installation) ---
    def org_status(self, slug: str) -> OrgStatus: ...

    def invite_member(self, slug: str, login: str) -> InviteResult: ...

    def is_active_member(self, slug: str, login: str) -> bool: ...


class PyGithubClient:
    """PyGithub-backed :class:`GitHubClient`.

    Installation clients are resolved per org slug and cached; PyGithub refreshes
    the underlying installation token automatically, so a cached client keeps
    working across the ~1 h token lifetime.
    """

    def __init__(
        self,
        *,
        oauth_client_id: str,
        oauth_client_secret: str,
        app_id: str,
        app_private_key: str,
        redirect_uri: str,
    ) -> None:
        self._redirect_uri = redirect_uri
        # OAuth App handle (participant identity).
        self._oauth = Github().get_oauth_application(
            oauth_client_id, oauth_client_secret
        )
        # GitHub App auth (installation invitations).
        self._app_auth = Auth.AppAuth(app_id, app_private_key)
        self._integration = GithubIntegration(auth=self._app_auth)
        self._install_clients: dict[str, Github] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ OAuth
    def oauth_login_url(self, state: str) -> str:
        # Empty scope (identity only) is PyGithub's default; redirect_uri must
        # match the OAuth App configuration.
        return self._oauth.get_login_url(redirect_uri=self._redirect_uri, state=state)

    def exchange_code_for_login(self, code: str, state: str) -> str | None:
        try:
            access = self._oauth.get_access_token(code, state=state)
            user_gh = Github(auth=Auth.Token(access.token))
            return user_gh.get_user().login
        except GithubException:
            logger.warning("OAuth code exchange / identity lookup failed", exc_info=True)
            return None

    # ----------------------------------------------------------- installation
    def _installation_github(self, slug: str) -> Github | None:
        """Return an installation-authenticated client for ``slug`` (cached).

        Returns ``None`` when the GitHub App is not installed on the org (or the
        org does not exist), which GitHub reports as a 404 on the installation
        lookup.
        """
        with self._lock:
            cached = self._install_clients.get(slug)
            if cached is not None:
                return cached
        try:
            installation = self._integration.get_org_installation(slug)
            install_auth = self._app_auth.get_installation_auth(installation.id)
            client = Github(auth=install_auth)
        except UnknownObjectException:
            return None
        except GithubException:
            logger.warning("Installation lookup failed (org=%s)", slug, exc_info=True)
            raise
        with self._lock:
            self._install_clients[slug] = client
        return client

    def _invalidate(self, slug: str) -> None:
        with self._lock:
            self._install_clients.pop(slug, None)

    def org_status(self, slug: str) -> OrgStatus:
        try:
            client = self._installation_github(slug)
        except GithubException as exc:
            return OrgStatus("error", f"Unexpected response from GitHub ({exc.status}).")
        if client is None:
            return OrgStatus(
                "not_installed",
                "The QR Org Join GitHub App is not installed on this organization "
                "(or the organization does not exist). Install the app to enable joins.",
            )
        try:
            client.get_organization(slug)
        except UnknownObjectException:
            return OrgStatus(
                "missing",
                "This organization no longer exists on GitHub. You can remove it from the list.",
            )
        except GithubException as exc:
            return OrgStatus("error", f"Unexpected response from GitHub ({exc.status}).")
        return OrgStatus(
            "ok", "The GitHub App is installed and can send invitations for this org."
        )

    def is_active_member(self, slug: str, login: str) -> bool:
        try:
            client = self._installation_github(slug)
            if client is None:
                return False
            org = client.get_organization(slug)
            user = client.get_user(login)
            return org.has_in_members(user)
        except GithubException:
            return False

    def invite_member(self, slug: str, login: str) -> InviteResult:
        try:
            client = self._installation_github(slug)
        except GithubException:
            return InviteResult("error")
        if client is None:
            return InviteResult("not_installed")

        try:
            org = client.get_organization(slug)
            user = client.get_user(login)
        except UnknownObjectException:
            # Unknown user login (or org) — treat as a normal error the UI reports.
            return InviteResult("error")
        except GithubException:
            logger.warning("Invite prep failed (org=%s)", slug, exc_info=True)
            self._invalidate(slug)
            return InviteResult("error")

        try:
            org.invite_user(user=user, role=_MEMBER_ROLE)
            logger.info("Invitation created (org=%s, state=pending)", slug)
            return InviteResult("invited", "pending", self._try_assign_copilot(org, slug, login))
        except RateLimitExceededException:
            logger.warning("Invite rate limited (org=%s)", slug)
            return InviteResult("rate_limited")
        except GithubException as exc:
            # 422 = already a member / already invited: report a friendly "in".
            if exc.status == 422 or self.is_active_member(slug, login):
                logger.info("Join no-op: already a member (org=%s)", slug)
                return InviteResult(
                    "already_member", "active", self._try_assign_copilot(org, slug, login)
                )
            logger.warning("Invite failed (org=%s, status=%s)", slug, exc.status)
            return InviteResult("error")

    def _try_assign_copilot(self, org, slug: str, login: str) -> str:
        """Best-effort: reserve a Copilot seat for the (pending) member.

        Returns ``"assigned"`` on success, else ``""`` — never raises. A pending
        invitee gets a reserved seat that activates when they accept the invite.
        Orgs without a Copilot Business/Enterprise plan (no free seats, or that
        haven't granted the App the *GitHub Copilot Business* permission) simply
        skip this; the invitation still stands.
        """
        try:
            org.get_copilot().add_seats([login])
            logger.info("Copilot seat assigned (org=%s)", slug)
            return "assigned"
        except GithubException as exc:
            logger.info("Copilot seat not assigned (org=%s, status=%s)", slug, exc.status)
            return ""
        except Exception:  # noqa: BLE001 — never let a seat error fail the invite
            logger.info("Copilot seat not assigned (org=%s)", slug, exc_info=True)
            return ""
