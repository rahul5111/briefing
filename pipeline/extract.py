"""Extract article body + cover image from a URL using trafilatura."""
from __future__ import annotations
import re
from urllib.parse import urljoin
import requests
import trafilatura


SKIP_DOMAINS = ("youtube.com", "youtu.be", "vimeo.com", "twitter.com", "x.com")
SKIP_SUFFIXES = (".pdf", ".zip", ".mp4", ".mov", ".jpg", ".png", ".gif")

_HEADERS = {"User-Agent": "briefing/1.0 (personal news aggregator)"}
_OG_IMAGE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_TWITTER_IMAGE = re.compile(
    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)


def _is_extractable(url: str) -> bool:
    lower = url.lower()
    if any(d in lower for d in SKIP_DOMAINS):
        return False
    if any(lower.endswith(s) for s in SKIP_SUFFIXES):
        return False
    return True


def _fetch_html(url: str) -> str | None:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15, allow_redirects=True)
        if r.status_code >= 400 or not r.text:
            return None
        return r.text
    except Exception:
        return None


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


def image(url: str) -> str | None:
    """Return the article's cover image URL (og:image or twitter:image)."""
    if not url:
        return None
    html = _fetch_html(url)
    if not html:
        return None
    for pat in (_OG_IMAGE, _TWITTER_IMAGE):
        m = pat.search(html[:20000])   # meta tags live near the top
        if m:
            src = m.group(1).strip()
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = urljoin(url, src)
            return src
    return None
