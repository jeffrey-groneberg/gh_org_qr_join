"""GitHub App webhooks: auto-onboard an org when the App is installed.

GitHub POSTs an ``installation`` event to ``/webhooks/github`` whenever the App
is installed on, or removed from, an organization. We verify the HMAC-SHA256
signature (GitHub's documented ``X-Hub-Signature-256`` scheme — the only thing
standing between us and forged "installed" events), then create or delete the
corresponding org in the store, recording its installation id.

This route is public (Easy Auth allows anonymous) and CSRF-exempt: it's a
server-to-server POST authenticated by the signature, not a browser form.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from flask import Blueprint, current_app, request

from models import Org
from org_store import OrgExistsError

webhooks_bp = Blueprint("webhooks", __name__)

logger = logging.getLogger(__name__)


def _config():
    return current_app.config["APP_CONFIG"]


def _store():
    return current_app.config["ORG_STORE"]


def _signature_ok(raw_body: bytes, header: str | None) -> bool:
    """Constant-time verify GitHub's X-Hub-Signature-256 (HMAC-SHA256)."""
    secret = _config().github_webhook_secret
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header)


@webhooks_bp.post("/webhooks/github")
def github_webhook():
    # 1) Authenticate the sender by signature BEFORE trusting any field. Hash the
    #    raw body exactly as received (re-serialized JSON would not match).
    raw = request.get_data()
    signature = request.headers.get("X-Hub-Signature-256")
    if not _signature_ok(raw, signature):
        logger.warning("Rejected GitHub webhook: bad or missing signature")
        return ("", 401)

    event = request.headers.get("X-GitHub-Event", "")
    payload = request.get_json(silent=True) or {}
    action = payload.get("action", "")

    # 2) Only installation lifecycle events onboard/offboard an org.
    if event != "installation":
        return ("", 204)  # acknowledged, ignored

    installation = payload.get("installation", {}) or {}
    account = installation.get("account", {}) or {}
    if account.get("type") != "Organization":
        return ("", 204)  # user-account installs don't map to a joinable org

    slug = Org.normalize_slug(account.get("login", ""))
    if not Org.is_valid_slug(slug):
        logger.warning("Webhook installation with invalid org login")
        return ("", 204)

    installation_id = installation.get("id")
    store = _store()

    # 3) React idempotently (GitHub retries deliveries).
    if action in ("created", "new_permissions_accepted", "unsuspend"):
        existing = store.get(slug)
        if existing is None:
            try:
                store.add(
                    Org(
                        slug=slug,
                        display_name=slug,
                        passcode=Org.generate_passcode(),
                        installation_id=installation_id,
                    )
                )
                logger.info("Org auto-onboarded via install (slug=%s)", slug)
            except OrgExistsError:
                store.set_installation_id(slug, installation_id)
        else:
            store.set_installation_id(slug, installation_id)
            logger.info("Install webhook refreshed existing org (slug=%s)", slug)

    elif action in ("deleted", "suspend"):
        if store.delete(slug):
            logger.info("Org removed via app uninstall (slug=%s)", slug)

    return ("", 204)
