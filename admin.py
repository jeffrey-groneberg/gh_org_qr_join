"""Admin org-list CRUD, gated behind Entra sign-in + the admin app role.

This manages only the app's list of joinable orgs (slug + display name +
default role) and renders each org's QR code for projecting. Member management
(invites, roles, removals) is intentionally left to GitHub.com.
"""

from __future__ import annotations

import secrets

import segno
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
from sqlalchemy.exc import IntegrityError

from auth import admin_required, current_admin
from extensions import db
from github import check_org_status
from models import VALID_ROLES, Org

admin_bp = Blueprint("admin", __name__)


def _config():
    return current_app.config["APP_CONFIG"]


def _ensure_admin_csrf() -> str:
    token = session.get("admin_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["admin_csrf"] = token
    return token


def _check_admin_csrf() -> None:
    submitted = request.form.get("csrf_token", "")
    expected = session.get("admin_csrf", "")
    if not expected or not secrets.compare_digest(submitted, expected):
        abort(400)


def _clean_role(raw: str) -> str:
    role = (raw or "").strip().lower()
    return role if role in VALID_ROLES else _config().default_member_role


@admin_bp.get("/admin")
@admin_required
def list_orgs():
    """List registered orgs with the add form and per-org actions."""
    orgs = Org.query.order_by(Org.display_name, Org.slug).all()
    admin = current_admin()
    return render_template(
        "admin_list.html",
        orgs=orgs,
        admin_name=admin.get("name") if admin else None,
        default_role=_config().default_member_role,
        error=session.pop("admin_error", None),
        notice=session.pop("admin_notice", None),
        check_result=session.pop("check_result", None),
        csrf_token=_ensure_admin_csrf(),
    )


@admin_bp.post("/admin/orgs")
@admin_required
def create_org():
    """Register a new org in the app's list."""
    _check_admin_csrf()
    slug = Org.normalize_slug(request.form.get("slug", ""))
    display_name = request.form.get("display_name", "").strip()
    role = _clean_role(request.form.get("member_role", ""))

    if not Org.is_valid_slug(slug):
        session["admin_error"] = "Enter a valid GitHub organization login (e.g. my-org)."
        return redirect(url_for("admin.list_orgs"))

    # Reject duplicates before hitting the GitHub API.
    if Org.query.filter_by(slug=slug).first() is not None:
        session["admin_error"] = f"Organization '{slug}' is already in the list."
        return redirect(url_for("admin.list_orgs"))

    # Validate against GitHub: only add an org the invite PAT can actually manage.
    result = check_org_status(_config().invite_token, slug)
    if result.status != "ok":
        if result.status == "missing":
            session["admin_error"] = (
                f"'{slug}' was not found on GitHub. Double-check the organization login."
            )
        else:
            session["admin_error"] = f"Cannot add '{slug}': {result.detail}"
        return redirect(url_for("admin.list_orgs"))

    org = Org(slug=slug, display_name=display_name or slug, member_role=role)
    db.session.add(org)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        session["admin_error"] = f"Organization '{slug}' is already in the list."
        return redirect(url_for("admin.list_orgs"))

    session["admin_notice"] = f"Added '{org.name}'."
    return redirect(url_for("admin.list_orgs"))


@admin_bp.post("/admin/orgs/<int:org_id>")
@admin_required
def update_org(org_id: int):
    """Rename an org or change its default join role (slug is immutable)."""
    _check_admin_csrf()
    org = db.session.get(Org, org_id)
    if org is None:
        abort(404)
    org.display_name = request.form.get("display_name", "").strip() or org.slug
    org.member_role = _clean_role(request.form.get("member_role", ""))
    db.session.commit()
    session["admin_notice"] = f"Updated '{org.name}'."
    return redirect(url_for("admin.list_orgs"))


@admin_bp.post("/admin/orgs/<int:org_id>/delete")
@admin_required
def delete_org(org_id: int):
    """Remove an org from the app's list (does not touch GitHub)."""
    _check_admin_csrf()
    org = db.session.get(Org, org_id)
    if org is None:
        abort(404)
    name = org.name
    db.session.delete(org)
    db.session.commit()
    session["admin_notice"] = f"Removed '{name}'."
    return redirect(url_for("admin.list_orgs"))


@admin_bp.post("/admin/orgs/<int:org_id>/check")
@admin_required
def check_org(org_id: int):
    """Validate an org against GitHub via the invite PAT and report the result."""
    _check_admin_csrf()
    org = db.session.get(Org, org_id)
    if org is None:
        abort(404)
    result = check_org_status(_config().invite_token, org.slug)
    session["check_result"] = {
        "org_id": org.id,
        "slug": org.slug,
        "name": org.name,
        "status": result.status,
        "detail": result.detail,
    }
    return redirect(url_for("admin.list_orgs"))


@admin_bp.get("/admin/orgs/<int:org_id>/qr")
@admin_required
def org_qr(org_id: int):
    """Full-screen QR code for an org, for projecting to participants."""
    config = _config()
    org = db.session.get(Org, org_id)
    if org is None:
        abort(404)
    target = config.org_join_url(org.slug)
    qr_svg = segno.make(target, error="m").svg_inline(scale=10)
    return render_template("admin_qr.html", org=org, qr_svg=qr_svg, target=target)
