"""Read/write feed.json and generate rss.xml."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from feedgen.feed import FeedGenerator
from . import config


def load() -> dict:
    if config.MANIFEST_PATH.exists():
        return json.loads(config.MANIFEST_PATH.read_text())
    return {"stories": []}


def save(manifest: dict) -> None:
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    config.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def write_rss(manifest: dict) -> None:
    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.title(config.SITE_TITLE)
    fg.link(href=config.SITE_URL, rel="alternate")
    fg.description(config.SITE_DESCRIPTION)
    fg.language("en")

    for s in manifest.get("stories", [])[:100]:
        fe = fg.add_entry()
        fe.id(s["id"])
        fe.title(s["title"])
        fe.description(s.get("summary", ""))
        fe.link(href=s.get("source_url") or s.get("hn_permalink", ""))
        fe.published(s["published_at"])
        audio_url = f"{config.CDN_BASE}/{s['audio_path']}" if config.CDN_BASE else s["audio_path"]
        fe.enclosure(audio_url, str(s.get("audio_bytes", 0)), "audio/mpeg")

    fg.rss_file(str(config.RSS_PATH), pretty=True)
