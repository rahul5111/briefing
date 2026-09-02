"""Reddit adapter via the public JSON endpoints (no auth).

Rate-limited to ~60 req/min for anonymous callers, which is fine for the
occasional batch. We honor Reddit's User-Agent guideline.
"""
from __future__ import annotations
import time
import requests
from .base import Candidate


UA = "briefing/1.0 (personal news aggregator)"


def fetch(cfg: dict) -> list[Candidate]:
    subreddit = cfg["subreddit"]
    listing = cfg.get("listing", "top")           # hot | new | top | rising
    when = cfg.get("when", "week")                # for top: hour | day | week | month
    min_score = int(cfg.get("min_score", 500))
    lookback_hours = int(cfg.get("lookback_hours", 168))
    max_items = int(cfg.get("max_items", 25))

    params = {"limit": max(max_items, 25)}
    if listing == "top":
        params["t"] = when

    url = f"https://www.reddit.com/r/{subreddit}/{listing}.json"
    r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    posts = r.json().get("data", {}).get("children", [])

    cutoff = int(time.time()) - lookback_hours * 3600
    out: list[Candidate] = []
    for p in posts:
        d = p.get("data", {})
        ts = int(d.get("created_utc") or 0)
        if ts < cutoff:
            continue
        score = int(d.get("score") or 0)
        if score < min_score:
            continue
        if d.get("is_self"):
            link = None
            text = d.get("selftext") or ""
            if len(text) < 200:
                continue
        else:
            link = d.get("url_overridden_by_dest") or d.get("url")
            text = None
        title = (d.get("title") or "").strip()
        if not title or not (link or text):
            continue
        oid = d.get("id")
        out.append(Candidate(
            id=f"reddit-{subreddit}-{oid}",
            source=cfg["name"],
            title=title,
            url=link,
            text=text if d.get("is_self") else None,
            author=d.get("author") or "",
            score=score,
            created_at_ts=ts,
            permalink=f"https://www.reddit.com{d.get('permalink','')}",
            extra={"subreddit": subreddit, "num_comments": d.get("num_comments")},
        ))
        if len(out) >= max_items:
            break
    return out
