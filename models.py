"""Domain model for an organization.

Persisted in Cosmos DB as a small JSON document; the ``slug`` doubles as the
document ``id`` and partition key, so reads/writes are single-partition point
operations. No secrets are stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# GitHub org logins: 1-39 chars, alphanumeric or single hyphens, not edge hyphens.
_SLUG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

VALID_ROLES = {"member", "admin"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Org:
    """A GitHub organization participants can self-join."""

    slug: str
    display_name: str = ""
    member_role: str = "member"
    created_at: str = field(default_factory=_now_iso)

    @property
    def id(self) -> str:
        # The Cosmos document id / partition key is the slug.
        return self.slug

    @property
    def name(self) -> str:
        return self.display_name or self.slug

    def to_item(self) -> dict:
        """Serialize to a Cosmos document."""
        return {
            "id": self.slug,
            "slug": self.slug,
            "display_name": self.display_name,
            "member_role": self.member_role,
            "created_at": self.created_at,
        }

    @classmethod
    def from_item(cls, item: dict) -> "Org":
        return cls(
            slug=item["slug"],
            display_name=item.get("display_name", ""),
            member_role=item.get("member_role", "member"),
            created_at=item.get("created_at", ""),
        )

    @staticmethod
    def normalize_slug(raw: str) -> str:
        return (raw or "").strip().lstrip("@").strip("/").lower()

    @staticmethod
    def is_valid_slug(slug: str) -> bool:
        return bool(_SLUG_RE.match(slug or ""))
