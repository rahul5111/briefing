"""One-shot: re-inject paragraph breaks into every stored summary and
re-run TTS in place. Only needed for the pre-fix corpus (before the
normalize.py paragraph-preservation fix landed). All new stories from
the pipeline already carry paragraph breaks through to TTS.

Heuristic: group sentences into paragraphs of 3, unless a sentence
starts with a topic-shift marker ("Meanwhile", "However", "In other
news", etc.) — those always start a new paragraph.

Usage:
    python -m pipeline.repar_and_retts            # touch all stories
    python -m pipeline.repar_and_retts <story_id> # single story
    python -m pipeline.repar_and_retts --dry      # preview, no writes
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

from . import config, tts, normalize


# Sentence-initial words that always start a new paragraph.
TOPIC_SHIFT_MARKERS = {
    "Meanwhile", "However", "Elsewhere", "Separately", "Additionally",
    "Also", "Furthermore", "In other news", "In related news", "In addition",
    "On the other hand", "By contrast", "Beyond that", "Later",
}

SENTENCES_PER_PARAGRAPH = 3


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _reparagraph(text: str) -> str:
    """Split into sentences, then re-group into paragraphs of ~3 or on a
    topic-shift marker. Deterministic — no LLM."""
    sents = _sentences(text)
    if not sents:
        return text
    paragraphs: list[list[str]] = [[]]
    for s in sents:
        first_word = s.split(" ", 1)[0].strip(",.")
        # Compare against markers by first 1-3 words (handles "In other news")
        head_1 = first_word
        head_2 = " ".join(s.split()[:2]).rstrip(",.")
        head_3 = " ".join(s.split()[:3]).rstrip(",.")
        is_shift = head_1 in TOPIC_SHIFT_MARKERS or head_2 in TOPIC_SHIFT_MARKERS or head_3 in TOPIC_SHIFT_MARKERS
        if paragraphs[-1] and (is_shift or len(paragraphs[-1]) >= SENTENCES_PER_PARAGRAPH):
            paragraphs.append([])
        paragraphs[-1].append(s)
    return "\n\n".join(" ".join(p) for p in paragraphs if p)


def _walk_stories(only_id: str | None) -> Iterable[dict]:
    doc = json.loads(config.MANIFEST_PATH.read_text())
    for s in doc["stories"]:
        if only_id and s["id"] != only_id:
            continue
        yield s


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("story_id", nargs="?")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args(argv)

    doc = json.loads(config.MANIFEST_PATH.read_text())
    changed = 0
    for s in doc["stories"]:
        if args.story_id and s["id"] != args.story_id:
            continue

        original = s.get("summary", "")
        if not original.strip():
            continue

        # Already paragraphed (new pipeline)? Skip.
        if original.count("\n\n") >= 1:
            continue

        repar = _reparagraph(original)
        paras = repar.count("\n\n") + 1
        print(f"[{s['id']:<50s}] {paras} paragraph(s)")

        if args.dry:
            continue

        # Persist the re-paragraphed summary for future runs (also feeds
        # any re-TTS after this).
        s["summary"] = repar

        # Re-TTS in place. The audio_path stays the same so no manifest
        # or front-end updates needed.
        audio_path = config.DATA_DIR / s["audio_path"]
        try:
            normalized = normalize.normalize(repar)
            stats = tts.synth(normalized, audio_path, s.get("main") or s.get("category") or "default")
            s["audio_duration_s"] = round(stats["duration_s"], 1)
            s["audio_bytes"] = audio_path.stat().st_size
            s["tts_chunks"] = stats["chunks_synthed"]
            s["tts_voice"] = stats["voice"]
            print(f"    → {stats['chunks_synthed']} chunks, {stats['duration_s']:.1f}s")
            changed += 1
        except Exception as e:
            print(f"    FAILED: {e}")

    if changed and not args.dry:
        config.MANIFEST_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
        print(f"\nwrote {config.MANIFEST_PATH} ({changed} stories re-synthesised)")
    elif not changed:
        print("\nno stories needed re-paragraphing")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
