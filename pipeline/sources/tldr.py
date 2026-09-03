"""TLDR newsletter scraper.

TLDR publishes free daily editions (tech, ai, webdev, infosec, design,
founders, ...) at https://tldr.tech/{variant}/YYYY-MM-DD. Each edition is
a curated pick of the day's most important stories in that vertical — the
same content you would otherwise get by subscribing via email.

Each story on the page is a `<article>` containing an `<a>` link with an
`<h3>` title inside. We pair them by DOM structure, strip TLDR's UTM
parameters, and skip sponsored/internal links.

Config in sources.yaml:

  - name: tldr_tech
    type: tldr
    variant: tech          # one of: tech ai webdev infosec design founders
    lookback_days: 3       # scrape today + previous N days
    max_items: 20
"""
from __future__ import annotations
import re
import time
from datetime import date, timedelta
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode
import requests
from bs4 import BeautifulSoup

from .base import Candidate


UA = {"User-Agent": "Mozilla/5.0 (compatible; briefing/1.0)"}
_MIN_READ = re.compile(r"\(\s*\d+\s*minute\s*read\s*\)\s*$", re.I)


def _strip_utm(url: str) -> str:
    try:
        p = urlparse(url)
        qs = {k: v for k, v in parse_qs(p.query).items()
              if not k.lower().startswith("utm_")
              and k.lower() not in ("mc_cid", "mc_eid", "src")}
        return urlunparse(p._replace(query=urlencode(qs, doseq=True)))
    except Exception:
        return url


def _is_sponsored(a) -> bool:
    """TLDR marks sponsors — usually inside a section with 'sponsor' in the
    heading or the link text ends with '(Sponsor)'. Best-effort filter."""
    text = a.get_text(" ", strip=True).lower()
    if "sponsor" in text:
        return True
    # walk up to a heading section
    for anc in a.parents:
        if anc.name in ("section", "div"):
            heading = anc.find(["h2", "h3"])
            if heading and "sponsor" in heading.get_text(strip=True).lower():
                return True
    return False


def _parse_issue(html: str, variant: str, issue_url: str,
                 issue_ts: int) -> list[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Candidate] = []
    seen: set[str] = set()
    for h3 in soup.find_all("h3"):
        title_raw = h3.get_text(" ", strip=True)
        if not _MIN_READ.search(title_raw):
            continue
        title = _MIN_READ.sub("", title_raw).strip()
        parent_a = h3.find_parent("a", href=True)
        if not parent_a:
            continue
        href = parent_a["href"]
        if not href.startswith("http"):
            continue
        if "tldr.tech" in href:
            continue
        if _is_sponsored(parent_a):
            continue
        clean = _strip_utm(href)
        if clean in seen:
            continue
        seen.add(clean)
        # id uses the domain + a hash of title to survive URL redirects
        import hashlib
        h = hashlib.sha1(f"{variant}:{title}".encode("utf-8")).hexdigest()[:12]
        out.append(Candidate(
            id=f"tldr-{variant}-{h}",
            source=f"tldr_{variant}",
            title=title,
            url=clean,
            text=None,
            author="TLDR",
            score=350,   # curated newsletter → high default weight
            created_at_ts=issue_ts,
            permalink=issue_url,
            extra={"variant": variant, "issue_url": issue_url},
        ))
    return out


def fetch(cfg: dict) -> list[Candidate]:
    variant = cfg.get("variant", "tech")
    lookback_days = int(cfg.get("lookback_days", 2))
    max_items = int(cfg.get("max_items", 25))

    today = date.today()
    all_items: list[Candidate] = []
    for i in range(lookback_days + 1):
        d = today - timedelta(days=i)
        issue_url = f"https://tldr.tech/{variant}/{d.isoformat()}"
        try:
            r = requests.get(issue_url, headers=UA, timeout=15, allow_redirects=True)
        except Exception:
            continue
        if r.status_code != 200 or not r.text:
            continue
        issue_ts = int(time.mktime(d.timetuple()))
        all_items.extend(_parse_issue(r.text, variant, r.url, issue_ts))
        if len(all_items) >= max_items * 2:
            break

    # Prefer the newest issues; dedup by URL already done per issue
    all_items.sort(key=lambda c: c.created_at_ts, reverse=True)
    return all_items[:max_items]
