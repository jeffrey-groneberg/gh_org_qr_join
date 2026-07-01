"""Domain model for an organization.

Persisted in Cosmos DB as a small JSON document; the ``slug`` doubles as the
document ``id`` and partition key, so reads/writes are single-partition point
operations. No secrets are stored.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

# GitHub org logins: 1-39 chars, alphanumeric or single hyphens, not edge hyphens.
_SLUG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

# Passcode alphabet: uppercase letters + digits, with visually ambiguous
# characters removed (0/O, 1/I/L) so codes are easy to read aloud and type.
_PASSCODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PASSCODE_LENGTH = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Org:
    """A GitHub organization participants can self-join."""

    slug: str
    display_name: str = ""
    passcode: str = ""
    installation_id: int | None = None
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
            "passcode": self.passcode,
            "installation_id": self.installation_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_item(cls, item: dict) -> "Org":
        return cls(
            slug=item["slug"],
            display_name=item.get("display_name", ""),
            passcode=item.get("passcode", ""),
            installation_id=item.get("installation_id"),
            created_at=item.get("created_at", ""),
        )

    @staticmethod
    def normalize_slug(raw: str) -> str:
        return (raw or "").strip().lstrip("@").strip("/").lower()

    @staticmethod
    def is_valid_slug(slug: str) -> bool:
        return bool(_SLUG_RE.match(slug or ""))

    @staticmethod
    def generate_passcode() -> str:
        """Return a fresh random join passcode."""
        return "".join(
            secrets.choice(_PASSCODE_ALPHABET) for _ in range(PASSCODE_LENGTH)
        )

    @staticmethod
    def normalize_passcode(raw: str) -> str:
        """Normalize user input for comparison (uppercase, no spaces/hyphens)."""
        return re.sub(r"[\s-]", "", (raw or "")).upper()

    def passcode_matches(self, submitted: str) -> bool:
        """True if a non-empty submitted code matches this org's passcode."""
        if not self.passcode:
            return False
        return secrets.compare_digest(
            self.normalize_passcode(submitted), self.passcode.upper()
        )

