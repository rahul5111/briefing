"""Hacker News via Algolia."""
from __future__ import annotations
import time
import requests
from .base import Candidate


def fetch(cfg: dict) -> list[Candidate]:
    min_score = int(cfg.get("min_score", 150))
    lookback_hours = int(cfg.get("lookback_hours", 168))   # 7 days default
    max_items = int(cfg.get("max_items", 40))
    tags = cfg.get("tags", "story")   # story | show_hn | ask_hn | front_page

    cutoff = int(time.time()) - lookback_hours * 3600
    params = {
        "tags": tags,
        "numericFilters": f"points>{min_score},created_at_i>{cutoff}",
        "hitsPerPage": max_items,
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
        oid = str(h["objectID"])
        out.append(Candidate(
            id=f"hn-{oid}",
            source=cfg["name"],
            title=h.get("title") or "",
            url=h.get("url"),
            text=h.get("story_text"),
            author=h.get("author") or "",
            score=int(h.get("points") or 0),
            created_at_ts=int(h.get("created_at_i") or 0),
            permalink=f"https://news.ycombinator.com/item?id={oid}",
        ))
    return out
