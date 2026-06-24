"""Database models.

Only non-secret org metadata is persisted. Invitations are performed with a
single classic PAT held in the environment, so no per-org credential is stored.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from extensions import db

# GitHub org logins: 1-39 chars, alphanumeric or single hyphens, not edge hyphens.
_SLUG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

VALID_ROLES = {"member", "admin"}


class Org(db.Model):
    """A GitHub organization participants can self-join."""

    __tablename__ = "orgs"

    id = db.Column(db.Integer, primary_key=True)
    # The GitHub org login/slug (what the API and URLs use). Unique, normalised.
    slug = db.Column(db.String(39), unique=True, nullable=False, index=True)
    # Human-friendly name shown in the UI. Falls back to slug if blank.
    display_name = db.Column(db.String(120), nullable=False, default="")
    # Role granted to joining members: "member" or "admin".
    member_role = db.Column(db.String(10), nullable=False, default="member")
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    @property
    def name(self) -> str:
        return self.display_name or self.slug

    @staticmethod
    def normalize_slug(raw: str) -> str:
        return (raw or "").strip().lstrip("@").strip("/").lower()

    @staticmethod
    def is_valid_slug(slug: str) -> bool:
        return bool(_SLUG_RE.match(slug or ""))
