"""Helpers for validating organizations against the GitHub API.

A single classic PAT (``admin:org``) is used. ``check_org_status`` distinguishes
three meaningful outcomes for the admin UI:

  * ``ok``        -> the org exists and the PAT can manage members (send invites).
  * ``no_access`` -> the org exists, but the PAT cannot manage it (not an owner,
                     or no access at all).
  * ``missing``   -> the org does not exist on GitHub (e.g. deleted or renamed) —
                     the admin should remove it from the list.
  * ``error``     -> a transient/network problem or an invalid token.
"""

from __future__ import annotations

from typing import NamedTuple

import requests

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
HTTP_TIMEOUT = (5, 10)

# Shared connection-pooled HTTP session.
_http = requests.Session()


class OrgStatus(NamedTuple):
    status: str  # "ok" | "no_access" | "missing" | "error"
    detail: str


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


def check_org_status(token: str, slug: str) -> OrgStatus:
    """Validate ``slug`` against GitHub using the invite ``token``."""
    headers = _headers(token)

    # 1) Does the org exist at all?
    try:
        resp = _http.get(
            f"{GITHUB_API_URL}/orgs/{slug}", headers=headers, timeout=HTTP_TIMEOUT
        )
    except requests.RequestException:
        return OrgStatus("error", "Could not reach GitHub. Please try again.")

    if resp.status_code == 404:
        return OrgStatus(
            "missing",
            "This organization no longer exists on GitHub. You can remove it from the list.",
        )
    if resp.status_code == 401:
        return OrgStatus("error", "The invite token is invalid or expired.")
    if resp.status_code != 200:
        return OrgStatus(
            "error", f"Unexpected response from GitHub ({resp.status_code})."
        )

    # 2) The org exists — can the PAT actually manage (invite) members? Creating
    #    invitations requires the token owner to be an org owner ("admin" role).
    try:
        membership = _http.get(
            f"{GITHUB_API_URL}/user/memberships/orgs/{slug}",
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException:
        return OrgStatus("error", "Could not reach GitHub. Please try again.")

    if membership.status_code == 200:
        role = membership.json().get("role")
        if role == "admin":
            return OrgStatus(
                "ok", "Organization exists and the invite token can send invitations."
            )
        return OrgStatus(
            "no_access",
            "Organization exists, but the invite token is not an owner, so it "
            "cannot send invitations.",
        )
    if membership.status_code in (403, 404):
        return OrgStatus(
            "no_access",
            "Organization exists, but the invite token has no access to it.",
        )
    return OrgStatus(
        "error", f"Unexpected response from GitHub ({membership.status_code})."
    )
