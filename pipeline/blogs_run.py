"""Blog ingestion pipeline. Separate manifest (`blogs.json`) so it doesn't
mix with the news feed. Weekly cadence (blog posts are slow), 30-day
retention (user wants a 1-month clock per entry).

Two summary passes per blog entry:

  summary_short — 100-160 words, for the card. Plain-text hook.
  summary_long  — 600-1500 words, for the reader + TTS audio. Variable
                  length so technical posts don't get squeezed into a
                  news-briefing template.

Both summaries share the TECH pronunciation dict from normalize.py
so Kokoro reads Kubernetes / Postgres / Langchain / etc. correctly.

    python -m pipeline.blogs_run             # full run
    python -m pipeline.blogs_run --dry       # fetch+refine only, no TTS
    python -m pipeline.blogs_run --limit N   # process at most N new entries
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import yaml
from slugify import slugify

from . import config, extract, normalize, tts
from google import genai


BLOGS_YAML = Path(__file__).parent / "blogs.yaml"
BLOGS_MANIFEST = config.DATA_DIR / "blogs.json"
BLOGS_AUDIO_DIR = config.DATA_DIR / "blogs-audio"
RETENTION_DAYS = 30
CHUNK_TARGET = 900          # target word count for long summary
CHUNK_MIN = 300             # blog posts are variable; some source posts are 500w themselves
CHUNK_MAX = 1600


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _call(prompt: str, max_tokens: int, temperature: float = 0.3) -> str | None:
    try:
        resp = _get_client().models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        return (resp.text or "").strip() or None
    except Exception as e:
        print(f"    Gemini error: {e}")
        return None


SHORT_PROMPT = """Summarise this technical blog post as a 100-160 word HOOK
paragraph for a reader-card.

Include:
- What the post is about, in one sentence.
- The key argument or finding.
- Why a working software engineer would open it.

Do NOT:
- Pad with generic phrases ("This post explores…", "In this article…").
- Editorialise ("groundbreaking", "must-read").
- Include code snippets.
- Add attribution — the source is separately visible on the card.

Return ONLY the summary text.

Title: {title}
Author: {author}

Blog post:
{body}
"""


LONG_PROMPT = """Rewrite this technical blog post as a SPOKEN-audio reader
briefing. A neural voice will read it aloud. The reader is a senior
software engineer / product manager who wants the depth, not a
skimmable news blurb.

Length: 600-1500 words, chosen by the post's real complexity. A short
opinion post is 600-800. A meaty architecture post is 900-1200. A deep
paper walk-through is 1200-1500. Do not pad, do not truncate.

Include:
- The problem the post opens with, in a full sentence with concrete
  context (system, constraint, or observation).
- The main argument or design, walked through step by step.
- Any specific numbers, product names, algorithms, or protocols
  mentioned — spelled out cleanly in speech form.
- The trade-offs or caveats the author names.
- The conclusion / recommendation the post ends with.

Hard rules for SPOKEN delivery:
- Spell out numbers, versions, dates, currency, percentages, ports,
  status codes ("port 443" → "port four four three"; not "port
  four hundred forty three"; do spell "eighty" for HTTP 80).
- Spell out acronyms on first use with periods: "API" → "A. P. I.",
  "HTTPS" → "H. T. T. P. S.".
- Short sentences (12-22 words). No dashes, no parentheses, no
  semicolons, no lists, no colons — rephrase around them.
- Code snippets: describe in prose ("the function takes a request
  handler and returns a middleware factory") — never quote code
  literally.
- Attribution: name the blog's author once in the first two sentences
  ({author} writes… / {author} argues… / from {author}'s post…).
- Paragraph breaks are a real audio cue — use them to separate
  distinct beats. Aim for 5-8 paragraphs total.

Return ONLY the rewritten text.

Title: {title}
Author: {author}

Blog post:
{body}
"""


def _short_summary(title: str, author: str, body: str) -> str | None:
    return _call(
        SHORT_PROMPT.format(title=title, author=author, body=body[:6000]),
        max_tokens=300,
    )


def _long_summary(title: str, author: str, body: str) -> str | None:
    return _call(
        LONG_PROMPT.format(title=title, author=author, body=body[:20000]),
        max_tokens=3000,
    )


def _load_manifest() -> dict:
    if BLOGS_MANIFEST.exists():
        return json.loads(BLOGS_MANIFEST.read_text())
    return {"entries": []}


def _save_manifest(doc: dict) -> None:
    BLOGS_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    BLOGS_MANIFEST.write_text(json.dumps(doc, ensure_ascii=False, indent=2))


def _entry_id(source: str, url: str) -> str:
    h = hashlib.sha1(url.encode()).hexdigest()[:12]
    return f"blog-{source}-{h}"


def _reading_time(text: str) -> int:
    return max(1, round(len(text.split()) / 220))


def _prune_expired(entries: list[dict]) -> list[dict]:
    """Drop entries past their expires_at + delete their audio."""
    now = datetime.now(timezone.utc)
    kept: list[dict] = []
    for e in entries:
        try:
            expires = datetime.fromisoformat(e["expires_at"].replace("Z", "+00:00"))
        except Exception:
            expires = now + timedelta(days=RETENTION_DAYS)
        if expires > now:
            kept.append(e)
        else:
            print(f"  expired: {e['title'][:70]}")
            if e.get("audio_path"):
                p = config.DATA_DIR / e["audio_path"]
                if p.exists():
                    p.unlink()
    return kept


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=999)
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(BLOGS_YAML.read_text())
    doc = _load_manifest()
    existing_ids = {e["id"] for e in doc["entries"]}

    # 1. Prune expired
    doc["entries"] = _prune_expired(doc["entries"])

    # 2. Fetch new entries from each blog
    candidates: list[dict] = []
    for src in cfg.get("blogs", []):
        f = feedparser.parse(src["url"])
        max_items = src.get("max_items", 4)
        for entry in f.entries[:max_items]:
            url = entry.get("link") or entry.get("id")
            if not url:
                continue
            eid = _entry_id(src["name"], url)
            if eid in existing_ids:
                continue
            title = entry.get("title", "").strip()
            if not title:
                continue
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                pub = datetime(*published[:6], tzinfo=timezone.utc)
            else:
                pub = datetime.now(timezone.utc)
            candidates.append({
                "_source_cfg": src,
                "_url": url,
                "_title": title,
                "_published_at": pub,
                "_entry_summary": (entry.get("summary") or "")[:600],
            })

    # Sort by newest first, respect --limit
    candidates.sort(key=lambda c: c["_published_at"], reverse=True)
    candidates = candidates[: args.limit]
    print(f"\n{len(candidates)} new blog entries to process")

    # 3. Extract + summarise + TTS
    now = datetime.now(timezone.utc)
    new_entries: list[dict] = []
    for c in candidates:
        src = c["_source_cfg"]
        url = c["_url"]
        title = c["_title"]
        author = src["author"]
        print(f"\n[{src['name']}] {title[:70]}")

        # Extract body
        body = None
        try:
            body = extract.extract(url)
        except Exception as e:
            print(f"  extract failed: {e}")
        if not body or len(body.split()) < 200:
            print("  body too short / extract failed, skipping")
            continue

        image_url = None
        try:
            image_url = extract.image(url)
        except Exception:
            pass

        # Short summary (card hook)
        short = _short_summary(title, author, body)
        if not short:
            print("  short summary failed, skipping")
            continue

        # Long summary (reader + audio)
        long_s = _long_summary(title, author, body)
        if not long_s:
            print("  long summary failed, skipping")
            continue

        wc = len(long_s.split())
        if wc < CHUNK_MIN:
            print(f"  long summary too short ({wc}w), skipping")
            continue
        if wc > CHUNK_MAX:
            # Truncate to nearest paragraph
            paras = long_s.split("\n\n")
            acc: list[str] = []
            for p in paras:
                if sum(len(x.split()) for x in acc) + len(p.split()) > CHUNK_MAX:
                    break
                acc.append(p)
            long_s = "\n\n".join(acc)
            wc = len(long_s.split())

        # TTS
        eid = _entry_id(src["name"], url)
        slug = slugify(title)[:60]
        audio_rel = f"blogs-audio/{now.strftime('%Y-%m')}/{eid}-{slug}.mp3"
        audio_path = config.DATA_DIR / audio_rel

        audio_duration = 0
        tts_chunks = 0
        tts_voice = ""

        if not args.dry:
            print(f"  TTS -> {audio_path.name}  ({wc}w)")
            try:
                normalized = normalize.normalize(long_s)
                stats = tts.synth(normalized, audio_path, "TECH")
                audio_duration = round(stats["duration_s"], 1)
                tts_chunks = stats["chunks_synthed"]
                tts_voice = stats["voice"]
                print(f"    {tts_chunks} chunks, {audio_duration}s")
            except Exception as e:
                print(f"  TTS failed: {e}")
                continue

        entry = {
            "id": eid,
            "type": "blog",
            "title": title,
            "author": author,
            "source": src["name"],
            "source_display": src["display"],
            "source_url": url,
            "topics": src.get("topics", []),
            "published_at": c["_published_at"].isoformat(),
            "expires_at": (now + timedelta(days=RETENTION_DAYS)).isoformat(),
            "reading_time_min": _reading_time(body),
            "summary_short": short,
            "summary_long": long_s,
            "long_word_count": wc,
            "audio_path": audio_rel if audio_duration else "",
            "audio_duration_s": audio_duration,
            "tts_chunks": tts_chunks,
            "tts_voice": tts_voice,
            "image_url": image_url,
        }
        new_entries.append(entry)

        # Incremental save: persist after every successful entry so a mid-
        # run kill doesn't cost the entries already synthesised. Sort by
        # publish date so newest floats to the top.
        combined = new_entries + doc["entries"]
        combined.sort(key=lambda e: e["published_at"], reverse=True)
        interim = {**doc, "entries": combined}
        _save_manifest(interim)

    # 4. Final save (harmless duplicate of the last incremental save)
    combined = new_entries + doc["entries"]
    combined.sort(key=lambda e: e["published_at"], reverse=True)
    doc["entries"] = combined
    _save_manifest(doc)
    print(f"\nAdded {len(new_entries)} entries. Manifest holds {len(combined)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
