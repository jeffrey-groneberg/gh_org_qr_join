"""Participant flow: GitHub identity + self-join for a specific org.

A participant reaches ``/orgs/<slug>`` by scanning that org's QR code. They:
  1. Sign in with GitHub (OAuth App, empty scope) so we learn their login.
  2. Click "Join {org}", which creates an org invitation using the shared
     classic PAT (admin:org).
  3. Accept the invitation on GitHub to finish joining.

Only orgs that exist in the database can be joined, so the broadly-scoped PAT
can never be used to invite into an arbitrary org.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import requests
from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import logging

from models import Org

participants_bp = Blueprint("participants", __name__)

logger = logging.getLogger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
HTTP_TIMEOUT = (5, 10)

# Shared connection-pooled HTTP session for all GitHub calls.
_http = requests.Session()


def _config():
    return current_app.config["APP_CONFIG"]


def _store():
    return current_app.config["ORG_STORE"]


def _get_org_or_404(slug: str) -> Org:
    org = _store().get(slug)
    if org is None:
        abort(404)
    return org


def _is_active_member(token: str, slug: str, login: str) -> bool:
    """True if ``login`` is already an active member of the org.

    Used to turn a 403 from the invite call (e.g. an owner trying to "join" their
    own org) into a friendly "already a member" result instead of an error.
    """
    try:
        resp = _http.get(
            f"{GITHUB_API_URL}/orgs/{slug}/memberships/{login}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException:
        return False
    return resp.status_code == 200 and resp.json().get("state") == "active"


@participants_bp.get("/orgs/<slug>")
def org_page(slug: str):
    """Participant landing page for a single org (reached by scanning the QR)."""
    org = _get_org_or_404(slug)
    # Identity is org-independent; only show join state for the org in context.
    invited = session.get("invited") and session.get("invited_slug") == slug
    return render_template(
        "join.html",
        org=org,
        user=session.get("user_login"),
        invited=invited,
        invite_state=session.get("invite_state"),
        accept_url=f"https://github.com/orgs/{slug}/invitation",
        error=session.pop("flash_error", None),
    )


@participants_bp.get("/orgs/<slug>/login")
def login(slug: str):
    """Start the GitHub OAuth web flow (identity only) for this org."""
    config = _config()
    _get_org_or_404(slug)
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    session["join_slug"] = slug
    params = {
        "client_id": config.github_client_id,
        "redirect_uri": config.github_redirect_uri,
        "state": state,
        "scope": "",  # identity only — we never need any scope
        "allow_signup": "true",
    }
    return redirect(f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}")


@participants_bp.get("/callback")
def callback():
    """Handle the GitHub OAuth redirect: validate state, exchange code, get login."""
    config = _config()
    slug = session.get("join_slug")
    back = url_for("participants.org_page", slug=slug) if slug else url_for("admin.list_orgs")

    if request.args.get("error"):
        logger.info("GitHub sign-in cancelled by user (org=%s)", slug)
        session["flash_error"] = "GitHub sign-in was cancelled. Please try again to join."
        return redirect(back)

    expected_state = session.pop("oauth_state", None)
    returned_state = request.args.get("state")
    if not expected_state or not returned_state or not secrets.compare_digest(
        expected_state, returned_state
    ):
        logger.warning("OAuth state validation failed (org=%s)", slug)
        session["flash_error"] = "Sign-in could not be verified. Please try again."
        return redirect(back)

    code = request.args.get("code")
    if not code:
        session["flash_error"] = "Sign-in failed (no code returned). Please retry."
        return redirect(back)

    try:
        token_resp = _http.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": config.github_client_id,
                "client_secret": config.github_client_secret,
                "code": code,
                "redirect_uri": config.github_redirect_uri,
            },
            timeout=HTTP_TIMEOUT,
        )
        token_resp.raise_for_status()
        user_token = token_resp.json().get("access_token")
    except requests.RequestException:
        logger.warning("GitHub token exchange failed (org=%s)", slug, exc_info=True)
        session["flash_error"] = "Could not reach GitHub to sign you in. Please retry."
        return redirect(back)

    if not user_token:
        logger.info("GitHub returned no access token (org=%s)", slug)
        session["flash_error"] = "GitHub did not grant access. Please try again."
        return redirect(back)

    try:
        user_resp = _http.get(
            f"{GITHUB_API_URL}/user",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {user_token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            timeout=HTTP_TIMEOUT,
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()
    except requests.RequestException:
        logger.warning("Failed to read GitHub identity (org=%s)", slug, exc_info=True)
        session["flash_error"] = "Could not read your GitHub identity. Please retry."
        return redirect(back)

    login_name = user_data.get("login")
    if not login_name:
        logger.warning("GitHub identity response missing login (org=%s)", slug)
        session["flash_error"] = "GitHub identity was incomplete. Please retry."
        return redirect(back)

    session["user_login"] = login_name
    session.pop("invited", None)
    session.pop("invite_state", None)
    session.pop("invited_slug", None)
    logger.info("Participant signed in to org context (org=%s)", slug)
    logger.debug("Signed-in GitHub user '%s' (org=%s)", login_name, slug)
    return redirect(back)


@participants_bp.post("/orgs/<slug>/join")
def join(slug: str):
    """Create the org invitation for the signed-in user via the shared PAT."""
    config = _config()
    org = _get_org_or_404(slug)
    login_name = session.get("user_login")
    if not login_name:
        return redirect(url_for("participants.org_page", slug=slug))

    # Passcode gate: only participants who know the org's passcode may be invited.
    if not org.passcode:
        logger.warning("Join attempted but org has no passcode set (org=%s)", slug)
        session["flash_error"] = (
            "Joining isn't enabled for this organization yet. Please ask the organizers."
        )
        return redirect(url_for("participants.org_page", slug=slug))
    if not org.passcode_matches(request.form.get("passcode", "")):
        logger.info("Join rejected: wrong passcode (org=%s)", slug)
        session["flash_error"] = "That passcode is not correct. Please check and try again."
        return redirect(url_for("participants.org_page", slug=slug))

    try:
        resp = _http.put(
            f"{GITHUB_API_URL}/orgs/{slug}/memberships/{login_name}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {config.invite_token}",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            # New members always join as "member"; org admins are promoted on
            # GitHub.com, not here.
            json={"role": "member"},
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException:
        logger.warning("Invite request to GitHub failed (org=%s)", slug, exc_info=True)
        session["flash_error"] = "Could not reach GitHub to send your invite. Please retry."
        return redirect(url_for("participants.org_page", slug=slug))

    if resp.status_code == 200:
        state = resp.json().get("state", "pending")
        session["invited"] = True
        session["invited_slug"] = slug
        session["invite_state"] = state
        logger.info("Invitation created (org=%s, state=%s)", slug, state)
    elif resp.status_code == 403:
        # A 403 also occurs when the signed-in user is already a member/owner
        # (GitHub won't let them set their own membership). Detect that and show
        # a friendly "already in" message instead of an authorization error.
        if _is_active_member(config.invite_token, slug, login_name):
            session["invited"] = True
            session["invited_slug"] = slug
            session["invite_state"] = "active"
            logger.info("Join no-op: already an active member (org=%s)", slug)
        else:
            logger.warning("Invite forbidden by GitHub (org=%s, status=403)", slug)
            session["flash_error"] = (
                "The invite service is not authorized for this organization. "
                "Please notify the organizer."
            )
    elif resp.status_code == 422:
        logger.warning("Invite unprocessable (org=%s, status=422)", slug)
        session["flash_error"] = (
            "GitHub could not process the invite right now (it may be rate "
            "limited). Please try again in a little while."
        )
    else:
        logger.warning("Invite failed (org=%s, status=%s)", slug, resp.status_code)
        session["flash_error"] = "Sending your invite failed. Please try again."

    return redirect(url_for("participants.org_page", slug=slug))


@participants_bp.get("/logout")
def logout():
    """Sign the participant out (clears GitHub identity + join state)."""
    for key in ("user_login", "invited", "invited_slug", "invite_state"):
        session.pop(key, None)
    slug = request.args.get("slug")
    if slug:
        return redirect(url_for("participants.org_page", slug=slug))
    return redirect(url_for("admin.list_orgs"))
