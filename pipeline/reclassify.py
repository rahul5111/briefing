"""Re-classify every story in the manifest with the new 8-cat taxonomy
(PLAN A3) and backfill `sources[]` for legacy single-source entries
(PLAN A4).

Chunked so a Gemini free-tier hiccup only wastes the current chunk. Skips
stories that already have both `main` and `sub` populated unless --force.

Usage:
    python -m pipeline.reclassify           # only touch un-migrated stories
    python -m pipeline.reclassify --force   # re-run against every story
    python -m pipeline.reclassify --dry     # print counts, no write
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

from . import config, categorize


CHUNK_SIZE = 25
CHUNK_SLEEP_S = 1.0


def needs_migration(story: dict, force: bool) -> bool:
    if force:
        return True
    return not (story.get("main") and story.get("sub"))


def backfill_sources(story: dict) -> bool:
    if isinstance(story.get("sources"), list) and story["sources"]:
        return False
    story["sources"] = [
        {
            "name": story.get("source", ""),
            "url": story.get("source_url"),
            "domain": story.get("source_domain", ""),
            "added_at": story.get("published_at", ""),
        }
    ]
    return True


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-classify every story")
    ap.add_argument("--dry", action="store_true", help="print counts, do not write")
    args = ap.parse_args(argv)

    path = Path(config.MANIFEST_PATH)
    if not path.exists():
        print(f"no manifest at {path}", file=sys.stderr)
        return 2
    doc = json.loads(path.read_text())
    stories: list[dict] = doc.get("stories", [])
    if not stories:
        print("empty manifest")
        return 0

    todo = [s for s in stories if needs_migration(s, args.force)]
    print(f"manifest: {len(stories)} stories · {len(todo)} need classification")

    backfill_count = sum(1 for s in stories if backfill_sources(s))
    print(f"backfilled sources[] on {backfill_count} legacy stories")

    if args.dry:
        return 0

    classified = 0
    for i in range(0, len(todo), CHUNK_SIZE):
        chunk = todo[i : i + CHUNK_SIZE]
        print(f"  chunk {i//CHUNK_SIZE + 1}: classifying {len(chunk)} stories…", end="", flush=True)
        try:
            labels = categorize.classify_batch(
                {
                    "title": s["title"],
                    "domain": s.get("source_domain", ""),
                    "summary": s.get("summary", ""),
                }
                for s in chunk
            )
        except Exception as e:
            print(f" FAILED: {e}")
            continue
        for s, lbl in zip(chunk, labels):
            s["main"] = lbl["main"]
            s["sub"] = lbl["sub"]
            s["category"] = lbl["main"]
            s["subcategory"] = lbl["sub"]
        classified += len(chunk)
        print(f" ok")
        time.sleep(CHUNK_SLEEP_S)

    # Report new distribution.
    dist: dict[str, int] = {}
    for s in stories:
        dist[s.get("main", "WORLD")] = dist.get(s.get("main", "WORLD"), 0) + 1
    print("\nDistribution after classify:")
    for k in ["AI","TECH","SCIENCE","SPORTS","US","INDIA","WORLD","BUSINESS"]:
        print(f"  {k:<10} {dist.get(k, 0)}")

    if classified or backfill_count:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
        print(f"\nwrote {path} ({classified} classified, {backfill_count} sources backfilled)")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
