"""Re-run refinement + TTS on a single existing story, for A/B testing.

Usage:  python -m pipeline.test_one <story_id>
Skips fetch/extract by re-hitting the URL directly and running the full
refinement stack. Writes new audio to /tmp/ so it doesn't clobber prod.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config, extract, refine, tts


def main(story_id: str) -> int:
    manifest = json.loads(config.MANIFEST_PATH.read_text())
    story = next((s for s in manifest["stories"] if s["id"] == story_id), None)
    if not story:
        print(f"story {story_id} not found")
        return 1

    url = story.get("source_url")
    print(f"Story: {story['title']}")
    print(f"URL:   {url}")

    if url:
        print("Re-extracting...")
        source = extract.extract(url)
        if not source:
            print("  extraction failed, falling back to old summary text")
            source = story["summary"]
    else:
        source = story["summary"]

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print("\nRefining...")
    refined = refine.refine(story["title"], source, story_id + "-retest", day)
    if not refined:
        print("refine failed")
        return 1

    print(f"\nRefined ({refined.word_count} words), passes: {', '.join(refined.passes_used)}")
    if refined.sanity_notes:
        print(f"Sanity flags: {refined.sanity_notes}")
    print("\n─── FINAL TEXT ───")
    print(refined.text)
    print("──────────────────\n")

    out = Path(f"/tmp/{story_id}-retest.mp3")
    print(f"TTS -> {out}")
    stats = tts.synth(refined.text, out, story.get("category", "tech"))
    print(f"  {stats['chunks_synthed']} chunks, {stats['duration_s']:.1f}s @ {stats['sample_rate']}Hz")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "hn-49537553"))
