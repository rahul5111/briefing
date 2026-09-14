"""Re-prune the current manifest with the new significance_v2 filter.

Uses the cached scoring from `data/audit_significance_v2.json` when
available (so we don't burn Gemini quota re-scoring), otherwise
re-scores. Drops stories with band=reject and their audio files. Writes
the reduced manifest back.

Also archives the pruned entries to `data/pruned_YYYY-MM-DD.json` so
they're recoverable if we tune the filter.

Usage:
    python -m pipeline.reprune            # apply
    python -m pipeline.reprune --dry      # preview only
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config, significance


AUDIT_PATH = config.ROOT / "data" / "audit_significance_v2.json"


def load_verdicts() -> dict[str, dict]:
    """Return {story_id: {score, band, reject_hits, reason}} from cache."""
    if not AUDIT_PATH.exists():
        return {}
    arr = json.loads(AUDIT_PATH.read_text())
    return {r["id"]: r for r in arr}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args(argv)

    doc = json.loads(config.MANIFEST_PATH.read_text())
    stories = doc.get("stories", [])
    if not stories:
        print("empty manifest")
        return 0

    verdicts = load_verdicts()
    if not verdicts:
        print("no cached audit; run `python -m pipeline.audit_significance_v2` first")
        return 2

    keep: list[dict] = []
    prune: list[dict] = []
    unscored: list[dict] = []
    for s in stories:
        v = verdicts.get(s["id"])
        if not v:
            unscored.append(s)
            keep.append(s)          # unscored is safest kept
            continue
        if v["band"] == "accept":
            keep.append(s)
        else:
            prune.append({**s, "_reprune_reason": v["reason"],
                          "_reprune_band": v["band"],
                          "_reprune_score": v["score"],
                          "_reprune_hits": v["reject_hits"]})

    print(f"manifest: {len(stories)} stories")
    print(f"  keep:     {len(keep)}")
    print(f"  prune:    {len(prune)}")
    print(f"  unscored: {len(unscored)} (kept as safe default)")

    # Break down by main-cat
    from collections import Counter
    cats_before = Counter(s.get("main") or "?" for s in stories)
    cats_after = Counter(s.get("main") or "?" for s in keep)
    print("\nPer-category (before → after):")
    for cat in sorted(cats_before):
        print(f"  {cat:>10s}: {cats_before[cat]:>3d} → {cats_after.get(cat, 0):>3d}  "
              f"(dropped {cats_before[cat] - cats_after.get(cat, 0)})")

    if args.dry:
        return 0

    # Archive the pruned entries
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive = config.ROOT / "data" / f"pruned_{day}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(json.dumps(prune, ensure_ascii=False, indent=2))
    print(f"\narchived {len(prune)} pruned entries → {archive}")

    # Delete the audio files for pruned stories (they're on disk under
    # site/public/data/audio/…). Skip if the file doesn't exist.
    audio_del = 0
    for p in prune:
        audio_rel = p.get("audio_path")
        if not audio_rel:
            continue
        audio_path = config.DATA_DIR / audio_rel
        if audio_path.exists():
            try:
                audio_path.unlink()
                audio_del += 1
            except OSError as e:
                print(f"  could not delete {audio_path}: {e}")
    print(f"deleted {audio_del} audio files")

    # Write reduced manifest
    doc["stories"] = keep
    config.MANIFEST_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    print(f"wrote reduced manifest ({len(keep)} stories) → {config.MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
