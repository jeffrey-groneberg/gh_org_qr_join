"""Admin authentication & authorization via App Service **Easy Auth**.

Authentication is handled by the platform (App Service built-in authentication
against Entra ID), configured to *allow unauthenticated requests* so that
participants pass through freely. When a user has signed in, App Service injects
their identity into every request as headers:

  * ``X-MS-CLIENT-PRINCIPAL-NAME`` -> display name / UPN
  * ``X-MS-CLIENT-PRINCIPAL``      -> base64 JSON of all claims (incl. app roles)

Admin authorization is decided by an Entra **app role** (default ``admin``)
present in those claims. The app never sees client secrets — Easy Auth owns the
OIDC flow at ``/.auth/login/aad`` and ``/.auth/logout``.
"""

from __future__ import annotations

import base64
import binascii
import json
from functools import wraps

import logging

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
)

auth_bp = Blueprint("auth", __name__)

logger = logging.getLogger(__name__)

# Claim types under which Entra app roles arrive in the Easy Auth principal.
_ROLE_CLAIM_TYPES = {
    "roles",
    "role",
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
}


def _decode_principal() -> dict | None:
    """Return the decoded Easy Auth client principal, or None if absent/invalid."""
    raw = request.headers.get("X-MS-CLIENT-PRINCIPAL")
    if not raw:
        return None
    try:
        return json.loads(base64.b64decode(raw))
    except (binascii.Error, ValueError, json.JSONDecodeError):
        return None


def _claim_value(principal: dict, types: tuple[str, ...]) -> str | None:
    for claim in principal.get("claims", []) or []:
        if claim.get("typ") in types and claim.get("val"):
            return claim["val"]
    return None


def current_admin() -> dict | None:
    """Identity of the signed-in admin, else None.

    Returns ``{"name": str, "roles": list[str]}`` when a principal is present.
    """
    principal = _decode_principal()
    if principal is None:
        return None

    roles = [
        claim["val"]
        for claim in (principal.get("claims", []) or [])
        if claim.get("typ") in _ROLE_CLAIM_TYPES and claim.get("val")
    ]
    name = (
        request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME")
        or _claim_value(principal, ("name", "preferred_username"))
        or "admin"
    )
    return {"name": name, "roles": roles}


def is_admin(admin: dict | None) -> bool:
    config = current_app.config["APP_CONFIG"]
    if not admin:
        return False
    wanted = config.entra_admin_role.lower()
    return any(r.lower() == wanted for r in admin.get("roles", []))


def _login_redirect():
    """Send the visitor to Easy Auth, returning them to the requested page."""
    return redirect(f"/.auth/login/aad?post_login_redirect_url={request.full_path}")


def admin_required(view):
    """Gate a view behind Easy Auth sign-in + the admin app role."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        admin = current_admin()
        if admin is None:
            logger.info("Unauthenticated access to %s; redirecting to sign-in", request.path)
            return _login_redirect()
        if not is_admin(admin):
            logger.warning(
                "Admin access denied to %s for '%s' (missing role)",
                request.path,
                admin.get("name"),
            )
            return render_template("forbidden.html", who=admin.get("name")), 403
        return view(*args, **kwargs)

    return wrapped


@auth_bp.get("/auth/login")
def login():
    return redirect("/.auth/login/aad?post_login_redirect_url=/admin")


@auth_bp.get("/auth/logout")
def logout():
    return redirect("/.auth/logout?post_logout_redirect_url=/")
