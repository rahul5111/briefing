"""Extract article body from a URL using trafilatura."""
from __future__ import annotations
import re
import trafilatura


SKIP_DOMAINS = ("youtube.com", "youtu.be", "vimeo.com", "twitter.com", "x.com")
SKIP_SUFFIXES = (".pdf", ".zip", ".mp4", ".mov", ".jpg", ".png", ".gif")


def _is_extractable(url: str) -> bool:
    lower = url.lower()
    if any(d in lower for d in SKIP_DOMAINS):
        return False
    if any(lower.endswith(s) for s in SKIP_SUFFIXES):
        return False
    return True


def extract(url: str) -> str | None:
    if not url or not _is_extractable(url):
        return None
    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=True)
        if not downloaded:
            return None
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        if not text:
            return None
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text.split()) < 120:
            return None
        return text
    except Exception:
        return None
