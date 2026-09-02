"""Fetch top HN stories via Algolia, return candidates for extraction."""
from __future__ import annotations
import time
from dataclasses import dataclass
import requests
from . import config


@dataclass
class Candidate:
    hn_id: str
    title: str
    url: str | None
    text: str | None
    author: str
    score: int
    created_at_ts: int
    hn_permalink: str


def fetch_top_stories() -> list[Candidate]:
    cutoff = int(time.time()) - config.HN_LOOKBACK_HOURS * 3600
    params = {
        "tags": "story",
        "numericFilters": f"points>{config.HN_MIN_SCORE},created_at_i>{cutoff}",
        "hitsPerPage": config.HN_MAX_STORIES,
    }
    r = requests.get(
        "https://hn.algolia.com/api/v1/search_by_date",
        params=params,
        timeout=20,
    )
    r.raise_for_status()
    hits = r.json().get("hits", [])
    out: list[Candidate] = []
    for h in hits:
        out.append(
            Candidate(
                hn_id=str(h["objectID"]),
                title=h.get("title") or "",
                url=h.get("url"),
                text=h.get("story_text"),
                author=h.get("author") or "",
                score=int(h.get("points") or 0),
                created_at_ts=int(h.get("created_at_i") or 0),
                hn_permalink=f"https://news.ycombinator.com/item?id={h['objectID']}",
            )
        )
    out.sort(key=lambda c: c.score, reverse=True)
    return out
