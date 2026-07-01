"""Admin org list, gated behind Entra sign-in + the admin app role.

Orgs are onboarded automatically when the GitHub App is installed on them (see
``webhooks.py``); this console lets an admin view that list, manage each org's
join passcode, check installation status, remove a stale entry, and project a
QR code. Member management (invites, roles, removals) is left to GitHub.com.
Persistence is the injected ``OrgStore`` on ``current_app.config["ORG_STORE"]``.
"""

from __future__ import annotations

import logging
import re

import segno
from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    session,
    url_for,
)

from auth import admin_required, current_admin
from models import Org

admin_bp = Blueprint("admin", __name__)

logger = logging.getLogger(__name__)


def _config():
    return current_app.config["APP_CONFIG"]


def _store():
    return current_app.config["ORG_STORE"]


def _github():
    return current_app.config["GITHUB"]


def _get_org_or_404(slug: str) -> Org:
    org = _store().get(slug)
    if org is None:
        abort(404)
    return org


def _qr_svg(target: str, scale: int = 10) -> str:
    """Render a QR as an inline SVG with a viewBox so it scales and stays
    centered regardless of the QR's intrinsic pixel size (which varies with the
    length of the encoded URL)."""
    raw = segno.make(target, error="m").svg_inline(scale=scale)

    def _add_viewbox(m: "re.Match[str]") -> str:
        w, h = m.group(1), m.group(2)
        return f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet" class="segno">'

    return re.sub(r'<svg width="(\d+)" height="(\d+)" class="segno">', _add_viewbox, raw, count=1)


@admin_bp.get("/admin")
@admin_required
def list_orgs():
    """List onboarded orgs with search/sort and per-org actions."""
    admin = current_admin()
    return render_template(
        "admin_list.html",
        orgs=_store().list(),
        admin_name=admin.get("name") if admin else None,
        error=session.pop("admin_error", None),
        notice=session.pop("admin_notice", None),
        check_result=session.pop("check_result", None),
    )


@admin_bp.post("/admin/orgs/<slug>/passcode")
@admin_required
def regenerate_passcode(slug: str):
    """Generate a fresh join passcode for an org (invalidates the old one)."""
    _get_org_or_404(slug)
    passcode = Org.generate_passcode()
    org = _store().set_passcode(slug, passcode)
    if org is None:
        abort(404)
    session["admin_notice"] = f"New join passcode for '{org.name}': {passcode}"
    logger.info("Org passcode regenerated (slug=%s)", slug)
    return redirect(url_for("admin.list_orgs"))


@admin_bp.post("/admin/orgs/<slug>/delete")
@admin_required
def delete_org(slug: str):
    """Remove a stale org from the list (e.g. a missed uninstall webhook)."""
    org = _get_org_or_404(slug)
    name = org.name
    _store().delete(slug)
    session["admin_notice"] = f"Removed '{name}'."
    logger.info("Org removed (slug=%s)", slug)
    return redirect(url_for("admin.list_orgs"))


@admin_bp.post("/admin/orgs/<slug>/check")
@admin_required
def check_org(slug: str):
    """Validate an org against GitHub via the GitHub App installation and report the result."""
    org = _get_org_or_404(slug)
    result = _github().org_status(org.slug)
    session["check_result"] = {
        "slug": org.slug,
        "name": org.name,
        "status": result.status,
        "detail": result.detail,
    }
    logger.info("Org checked (slug=%s, status=%s)", org.slug, result.status)
    return redirect(url_for("admin.list_orgs"))


@admin_bp.get("/admin/orgs/<slug>/qr")
@admin_required
def org_qr(slug: str):
    """Full-screen QR code for an org, for projecting to participants."""
    config = _config()
    org = _get_org_or_404(slug)
    target = config.org_join_url(org.slug)
    qr_svg = _qr_svg(target, scale=10)
    return render_template("admin_qr.html", org=org, qr_svg=qr_svg, target=target)
