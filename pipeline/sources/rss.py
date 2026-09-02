"""Generic RSS / Atom feed adapter.

Works for blogs, newsletters (Substack, Beehiiv, Ghost), most news sites, and
podcasts (audio enclosures are ignored — we regenerate our own audio).

Trafilatura still runs on the article URL downstream to extract clean body
text. If the feed itself includes full article HTML in `content:encoded`, we
use that as the text so the pipeline can skip a network round-trip.
"""
from __future__ import annotations
import calendar
import hashlib
import time
from urllib.parse import urlparse
import feedparser
from .base import Candidate


def _entry_ts(entry) -> int:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        v = getattr(entry, key, None) or entry.get(key)
        if v:
            try:
                return calendar.timegm(v)
            except (TypeError, ValueError):
                pass
    return int(time.time())


def _entry_id(entry, feed_slug: str, url: str | None) -> str:
    raw = entry.get("id") or url or entry.get("title") or ""
    h = hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"rss-{feed_slug}-{h}"


def _entry_text(entry) -> str | None:
    # Prefer content:encoded (full article) over summary (excerpt)
    contents = entry.get("content") or []
    if contents:
        best = max(contents, key=lambda c: len(c.get("value", "")))
        val = best.get("value", "")
        if val and len(val) > 400:
            return val
    summary = entry.get("summary") or entry.get("description") or ""
    if summary and len(summary) > 400:
        return summary
    return None


def fetch(cfg: dict) -> list[Candidate]:
    url = cfg["url"]
    max_items = int(cfg.get("max_items", 25))
    lookback_hours = int(cfg.get("lookback_hours", 168))
    feed_slug = cfg["name"]

    parsed = feedparser.parse(url, request_headers={"User-Agent": "briefing/1.0"})
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        return []

    cutoff = int(time.time()) - lookback_hours * 3600
    out: list[Candidate] = []
    for entry in parsed.entries[:max_items]:
        ts = _entry_ts(entry)
        if ts < cutoff:
            continue
        link = entry.get("link")
        if not link:
            continue
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        out.append(Candidate(
            id=_entry_id(entry, feed_slug, link),
            source=feed_slug,
            title=title,
            url=link,
            text=_entry_text(entry),
            author=str(entry.get("author") or ""),
            score=cfg.get("default_score", 100),
            created_at_ts=ts,
            permalink=link,
            extra={"feed_domain": urlparse(url).netloc},
        ))
    return out
