"""Score the current manifest against the new significance_v2 filter.

Reports: drop rate per category, top-10 accepts and top-10 rejects per
category, borderline-band sample. Does NOT modify the manifest. Use to
validate the filter before wiring into run.py.

    python -m pipeline.audit_significance_v2

Costs ~N/25 Gemini calls where N is the manifest size (batched at 25).
"""
from __future__ import annotations
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import config, significance


CHUNK_SIZE = 20


def main() -> int:
    doc = json.loads(config.MANIFEST_PATH.read_text())
    stories = doc.get("stories", [])
    if not stories:
        print("empty manifest")
        return 0

    print(f"Scoring {len(stories)} stories against significance_v2…")
    results: list[tuple[dict, significance.SignificanceV2]] = []
    for i in range(0, len(stories), CHUNK_SIZE):
        batch = stories[i : i + CHUNK_SIZE]
        items = [{
            "title": s["title"],
            "summary": s.get("summary", ""),
            "source": s.get("source", ""),
            "category": s.get("main") or s.get("category") or "",
        } for s in batch]
        try:
            scored = significance.score_v2_batch(items)
        except Exception as e:
            print(f"  chunk {i//CHUNK_SIZE + 1}: FAILED {e}")
            scored = [significance._FALLBACK_V2] * len(batch)
        results.extend(zip(batch, scored))
        print(f"  chunk {i//CHUNK_SIZE + 1}/{(len(stories)+CHUNK_SIZE-1)//CHUNK_SIZE}: "
              f"{sum(1 for r in scored if r.band=='accept')} accept, "
              f"{sum(1 for r in scored if r.band=='borderline')} borderline, "
              f"{sum(1 for r in scored if r.band=='reject')} reject")

    # Overall stats
    band_counts = Counter(r.band for _, r in results)
    total = len(results)
    print(f"\nOverall: {total} scored")
    for b in ("accept", "borderline", "reject"):
        n = band_counts.get(b, 0)
        print(f"  {b:>10s}: {n:>3d} ({100*n/total:.1f}%)")

    # Per category
    by_cat: dict[str, list[tuple[dict, significance.SignificanceV2]]] = defaultdict(list)
    for s, r in results:
        by_cat[s.get("main") or s.get("category") or "?"].append((s, r))
    print(f"\nPer main-category drop rate (band=reject):")
    for cat, rows in sorted(by_cat.items()):
        n_reject = sum(1 for _, r in rows if r.band == "reject")
        n_accept = sum(1 for _, r in rows if r.band == "accept")
        n_border = sum(1 for _, r in rows if r.band == "borderline")
        print(f"  {cat:>8s}: {len(rows):>3d}  accept={n_accept:>3d}  "
              f"border={n_border:>3d}  reject={n_reject:>3d}  "
              f"drop={100*n_reject/len(rows):.0f}%")

    # Sample rejects (worst) and accepts (best) for INDIA — where user
    # is most frustrated by noise
    india = by_cat.get("INDIA", [])
    if india:
        print(f"\nINDIA rejects (would be dropped) — top 10 by low score:")
        for s, r in sorted(india, key=lambda x: x[1].score)[:10]:
            if r.band != "reject":
                continue
            print(f"  [{r.score:.2f}] R={','.join(r.reject_hits)}  "
                  f"{s['title'][:80]}")
            print(f"         reason: {r.one_line_reason}")
        print(f"\nINDIA accepts (would be kept) — top 10 by high score:")
        for s, r in sorted(india, key=lambda x: -x[1].score)[:10]:
            if r.band != "accept":
                continue
            print(f"  [{r.score:.2f}] A={','.join(r.accept_hits)}  "
                  f"{s['title'][:80]}")

    # Cross-check: reject histogram — which rules fire most?
    reject_rule_hits: Counter = Counter()
    for _, r in results:
        for h in r.reject_hits:
            reject_rule_hits[h] += 1
    print(f"\nMost-fired REJECT rules:")
    for rule, n in reject_rule_hits.most_common(10):
        print(f"  {rule}: {n}")

    # Persist the full scoring to a file so we can iterate the prompt
    # without re-scoring everything.
    out_path = config.ROOT / "data" / "audit_significance_v2.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([
        {"id": s["id"], "title": s["title"], "main": s.get("main", ""),
         "score": r.score, "band": r.band,
         "accept_hits": r.accept_hits, "reject_hits": r.reject_hits,
         "tighter_penalties": r.tighter_penalties,
         "reason": r.one_line_reason}
        for s, r in results
    ], ensure_ascii=False, indent=2))
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
