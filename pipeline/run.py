"""Orchestrator: fetch → extract → dedup → refine (multi-pass) → tts → manifest."""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from slugify import slugify

from . import config, fetch, extract, dedup, refine, tts, manifest

DRY_RUN = os.environ.get("PIPELINE_DRY_RUN", "").lower() in ("1", "true", "yes")


def classify(title: str, url: str | None) -> str:
    """Very cheap category tag. Refine later."""
    t = (title + " " + (url or "")).lower()
    world_hits = ("bbc.com", "reuters.com", "aljazeera", "npr.org", "election",
                  "ukraine", "gaza", "china", "russia", "climate", "flood",
                  "earthquake", "un.org")
    if any(w in t for w in world_hits):
        return "world"
    return "tech"


def build_story(cand, source_text: str, summary: str, category: str) -> dict:
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    slug = slugify(cand.title)[:60]
    audio_rel = f"audio/{day}/{cand.hn_id}-{slug}.mp3"
    return {
        "id": f"hn-{cand.hn_id}",
        "title": cand.title,
        "summary": summary,
        "category": category,
        "source_url": cand.url,
        "source_domain": _domain(cand.url) if cand.url else "news.ycombinator.com",
        "hn_permalink": cand.hn_permalink,
        "hn_score": cand.score,
        "author": cand.author,
        "published_at": now.isoformat(),
        "created_at_ts": cand.created_at_ts,
        "audio_path": audio_rel,
        "word_count": len(summary.split()),
        "estimated_duration_s": round(len(summary.split()) / (config.TTS_WPM / 60)),
    }


def _domain(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def main() -> int:
    print("Fetching HN top stories...")
    candidates = fetch.fetch_top_stories()
    print(f"  {len(candidates)} candidates above score {config.HN_MIN_SCORE}")

    print("Deduping against recent publications...")
    keep_idx = dedup.dedup([c.title for c in candidates])
    candidates = [candidates[i] for i in keep_idx]
    print(f"  {len(candidates)} after dedup")

    existing = manifest.load()
    existing_ids = {s["id"] for s in existing["stories"]}

    new_stories: list[dict] = []
    for cand in candidates:
        story_id = f"hn-{cand.hn_id}"
        if story_id in existing_ids:
            continue

        print(f"\n[{cand.score}] {cand.title}")
        if cand.text and len(cand.text.split()) > 120:
            source_text = cand.text
            print("  using HN self-post text")
        elif cand.url:
            print(f"  extracting from {cand.url}")
            source_text = extract.extract(cand.url)
            if not source_text:
                print("  extraction failed, skipping")
                continue
        else:
            print("  no url and no text, skipping")
            continue

        category = classify(cand.title, cand.url)
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        story_id = f"hn-{cand.hn_id}"

        print(f"  refining (category={category})")
        try:
            refined = refine.refine(cand.title, source_text, story_id, day)
        except Exception as e:
            print(f"  refine failed: {e}")
            continue
        if not refined:
            print("  refine rejected, skipping")
            continue
        print(f"  refined: {refined.word_count} words | passes: {', '.join(refined.passes_used)}")
        if refined.sanity_notes:
            print(f"  sanity flags: {refined.sanity_notes[:120]}")

        if DRY_RUN:
            print("  DRY_RUN: skipping TTS")
            continue

        story = build_story(cand, source_text, refined.text, category)
        audio_path = config.DATA_DIR / story["audio_path"]
        print(f"  TTS -> {audio_path.name}")
        try:
            tts_stats = tts.synth(refined.text, audio_path, category)
            story["audio_bytes"] = audio_path.stat().st_size
            story["audio_duration_s"] = round(tts_stats["duration_s"], 1)
            story["tts_chunks"] = tts_stats["chunks_synthed"]
            story["tts_voice"] = tts_stats["voice"]
            print(f"    {tts_stats['chunks_synthed']} chunks, {tts_stats['duration_s']:.1f}s")
        except Exception as e:
            print(f"  TTS failed: {e}")
            continue

        new_stories.append(story)

    if not new_stories:
        print("\nNo new stories this run.")
        return 0

    existing["stories"] = sorted(
        new_stories + existing["stories"],
        key=lambda s: s["created_at_ts"],
        reverse=True,
    )
    manifest.save(existing)
    manifest.write_rss(existing)
    print(f"\nAdded {len(new_stories)} stories. Manifest updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
