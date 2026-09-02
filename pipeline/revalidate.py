"""Rerun the audio validator on already-generated mock MP3s (no TTS again)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

from . import audio_validate, config


def main(ids: list[str]) -> int:
    manifest = json.loads(config.MANIFEST_PATH.read_text())
    day_reviews = config.DATA_DIR / "reviews" / "2026-09-02"

    print(f"\n{'Story':<20} {'Dur':<8} {'WER':<7} {'CER':<7} {'Verdict':<10}")
    for sid in ids:
        mp3 = Path(f"/tmp/{sid}-mock.mp3")
        review = day_reviews / f"{sid}-mock.txt"
        if not mp3.exists() or not review.exists():
            print(f"{sid:<20} MISSING")
            continue
        # extract the 05_NORMALIZED section from the review file
        rev = review.read_text()
        sections = rev.split("═══")
        final = None
        for i, sec in enumerate(sections):
            if "05_NORMALIZED" in sec and i + 1 < len(sections):
                final = sections[i + 1].strip()
                break
        if not final:
            print(f"{sid:<20} NO_NORMALIZED_SECTION")
            continue
        v = audio_validate.validate(mp3, final)
        print(f"{sid:<20} {v.duration_s:.1f}s{'':<2} {v.wer:<7} {v.cer:<7} {v.verdict:<10}")
        if v.mismatched_words:
            for a, b in v.mismatched_words[:6]:
                print(f"    '{a}' → '{b}'")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["hn-49537553", "hn-49535526", "hn-49529621"]))
