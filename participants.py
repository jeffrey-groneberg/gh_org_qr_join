"""Participant flow: GitHub identity + self-join for a specific org.

A participant reaches ``/orgs/<slug>`` by scanning that org's QR code. They:
  1. Sign in with GitHub (OAuth App, empty scope) so we learn their login.
  2. Click "Join {org}", which creates an org invitation via the GitHub App's
     per-org installation token (least privilege: *Members: write*).
  3. Accept the invitation on GitHub to finish joining.

Only orgs that exist in the database can be joined, and invitations are sent
with an installation token scoped to that single org.
"""

from __future__ import annotations

import logging
import secrets

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

from models import Org

participants_bp = Blueprint("participants", __name__)

logger = logging.getLogger(__name__)


def _store():
    return current_app.config["ORG_STORE"]


def _github():
    return current_app.config["GITHUB"]


def _get_org_or_404(slug: str) -> Org:
    org = _store().get(slug)
    if org is None:
        abort(404)
    return org


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
        copilot=invited and session.get("invite_copilot"),
        accept_url=f"https://github.com/orgs/{slug}/invitation",
        error=session.pop("flash_error", None),
    )


@participants_bp.get("/orgs/<slug>/login")
def login(slug: str):
    """Start the GitHub OAuth web flow (identity only) for this org."""
    _get_org_or_404(slug)
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    session["join_slug"] = slug
    return redirect(_github().oauth_login_url(state))


@participants_bp.get("/callback")
def callback():
    """Handle the GitHub OAuth redirect: validate state, exchange code, get login."""
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

    login_name = _github().exchange_code_for_login(code, returned_state)
    if not login_name:
        session["flash_error"] = "Could not sign you in with GitHub. Please retry."
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
    """Create the org invitation for the signed-in user via the GitHub App."""
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

    result = _github().invite_member(slug, login_name)

    if result.outcome in ("invited", "already_member"):
        session["invited"] = True
        session["invited_slug"] = slug
        session["invite_state"] = result.state or "pending"
        session["invite_copilot"] = result.copilot == "assigned"
    elif result.outcome == "not_installed":
        logger.warning("Join blocked: app not installed (org=%s)", slug)
        session["flash_error"] = (
            "Joining isn't available for this organization yet. Please notify the organizer."
        )
    elif result.outcome == "rate_limited":
        session["flash_error"] = (
            "GitHub is rate limiting invitations right now. Please try again in a little while."
        )
    else:
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
