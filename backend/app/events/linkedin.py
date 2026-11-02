"""LinkedIn profile URLs, normalized so the same person is the same row whichever way the URL was written."""

import re
from urllib.parse import urlsplit

_PROFILE = re.compile(r"^/in/([^/?#]+)", re.IGNORECASE)
_LEGACY = re.compile(r"^/pub/([^?#]+?)/*$", re.IGNORECASE)
"""An old public profile, /pub/<name>/<a>/<b>/<c>: the trailing parts tell people with the same name apart."""


def normalize_profile_url(url: str | None) -> str | None:
    """'http://linkedin.com/in/Jane-Doe-123/?trk=x' -> 'https://www.linkedin.com/in/jane-doe-123'.

    An old /pub/ profile keeps its whole path, so two people with the same name stay two people. Returns None for
    anything that isn't a personal profile (company pages, posts, other sites).
    """
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None
    match = _PROFILE.match(parts.path)
    if match:
        return f"https://www.linkedin.com/in/{match.group(1).lower()}"
    legacy = _LEGACY.match(parts.path)
    if legacy:
        return f"https://www.linkedin.com/pub/{legacy.group(1).lower()}"
    return None
