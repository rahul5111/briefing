"""Orchestrator: multi-source fetch → extract → dedup → refine → tts → manifest."""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse
from slugify import slugify

from . import config, extract, dedup, refine, tts, manifest, categorize, geolocate, significance, enrich, audio_validate
from .sources import fetch_all, Candidate

DRY_RUN = os.environ.get("PIPELINE_DRY_RUN", "").lower() in ("1", "true", "yes")


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def build_story(cand: Candidate, summary: str, image_url: str | None) -> dict:
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    slug = slugify(cand.title)[:60]
    audio_rel = f"audio/{day}/{cand.id}-{slug}.mp3"
    return {
        "id": cand.id,
        "title": cand.title,
        "summary": summary,
        "main": "WORLD",                # filled by classifier below (PLAN A2)
        "sub": "Society & Culture",     # filled by classifier below
        "category": "WORLD",            # back-compat mirror of `main`
        "subcategory": "Society & Culture",
        "sources": [                    # PLAN A4 — cross-source enrichment
            {
                "name": cand.source,
                "url": cand.url,
                "domain": _domain(cand.url) or cand.extra.get("feed_domain", ""),
                "added_at": now.isoformat(),
            }
        ],
        "source": cand.source,
        "source_url": cand.url,
        "source_domain": _domain(cand.url) or cand.extra.get("feed_domain", ""),
        "source_permalink": cand.permalink,
        "score": cand.score,
        "author": cand.author,
        "published_at": now.isoformat(),
        "created_at_ts": cand.created_at_ts,
        "audio_path": audio_rel,
        "word_count": len(summary.split()),
        "estimated_duration_s": round(len(summary.split()) / (config.TTS_WPM / 60)),
        "image_url": image_url,
        "location": None,               # filled by geolocator batch below
    }


def _enrich_from_dups(dup_log: list, candidates: list[Candidate], existing_manifest: dict) -> None:
    """PLAN C4: when a new candidate is a semantic duplicate of a story
    already in the manifest, extract its article body, check whether it
    materially adds information, and if so re-synthesize + re-TTS the
    stored story. Always appends the new URL to the story's sources[].

    Safe by construction: any exception in extract, delta, synth, or TTS
    leaves the existing story untouched — dropping the candidate is the
    fallback, same as pre-Phase-2 behaviour.
    """
    published_dups = [h for h in dup_log if h.matched_kind == "published"]
    if not published_dups:
        return
    stories_by_title = {s["title"]: s for s in existing_manifest.get("stories", [])}
    merged = 0
    appended = 0
    for hit in published_dups:
        cand = candidates[hit.new_index]
        story = stories_by_title.get(hit.matched_title)
        if not story or not cand.url:
            continue

        # Extract new article body — prefer pre-fetched RSS text when available.
        text: str | None = None
        if cand.text and len(cand.text.split()) > 120:
            text = cand.text
        else:
            try:
                text = extract.extract(cand.url)
            except Exception as e:
                print(f"  enrich extract failed for {cand.source}: {e}")
                continue
        if not text or len(text.split()) < 60:
            continue

        # Always credit the new source (unless we already have that URL).
        now_iso = datetime.now(timezone.utc).isoformat()
        new_entry = {
            "name": cand.source,
            "url": cand.url,
            "domain": _domain(cand.url),
            "added_at": now_iso,
        }
        srcs = story.setdefault("sources", [])
        if not any(sr.get("url") == cand.url for sr in srcs):
            srcs.append(new_entry)
            appended += 1

        # Delta detection — cheap Gemini call.
        try:
            delta = enrich.detect_delta(story.get("summary", ""), text)
        except Exception as e:
            print(f"  enrich delta failed: {e}")
            continue
        if not delta["adds_material"]:
            print(f"  enrich [{cand.source[:12]:12s}]: delta {delta['delta_pct']}% — sources++ only")
            continue

        # Neutral synthesis (mid-weight call).
        try:
            synth = enrich.neutral_synthesize(
                existing_summary=story.get("summary", ""),
                existing_key_points=story.get("key_points"),
                new_article_text=text,
                new_facts=delta["new_facts"],
            )
        except Exception as e:
            print(f"  enrich synth failed: {e}")
            continue
        if not synth:
            continue

        # Persist the merged summary + re-TTS. On any TTS failure, leave
        # the summary/points patched but audio untouched — text feed is
        # still improved.
        story["summary"] = synth["summary"]
        story["key_points"] = synth["key_points"]
        story["word_count"] = len(synth["summary"].split())
        story["estimated_duration_s"] = round(
            len(synth["summary"].split()) / (config.TTS_WPM / 60)
        )
        audio_path = config.DATA_DIR / story["audio_path"]
        try:
            voice_cat = story.get("main") or story.get("category") or "default"
            stats = tts.synth(synth["summary"], audio_path, voice_cat)
            story["audio_bytes"] = audio_path.stat().st_size
            story["audio_duration_s"] = round(stats["duration_s"], 1)
            story["tts_chunks"] = stats["chunks_synthed"]
            story["tts_voice"] = stats["voice"]
            merged += 1
            print(
                f"  enrich [{cand.source[:12]:12s}]: MERGED delta {delta['delta_pct']}% → "
                f"{stats['duration_s']:.1f}s re-TTS"
            )
        except Exception as e:
            print(f"  enrich re-TTS failed for {story['id']}: {e}")
    if merged or appended:
        print(f"  enrich totals: {merged} merged+re-TTS'd, {appended} sources appended")


def main() -> int:
    print("Fetching from all configured sources...")
    candidates = fetch_all()
    print(f"\nTotal candidates: {len(candidates)}")

    existing = manifest.load()
    existing_ids = {s["id"] for s in existing["stories"]}

    # Drop already-processed items early so we don't waste work on dedup
    candidates = [c for c in candidates if c.id not in existing_ids]
    print(f"After dropping already-processed: {len(candidates)}")

    if not candidates:
        print("Nothing new to process.")
        return 0

    print("\nDeduping against manifest + within batch...")
    keep_idx, dup_log = dedup.dedup_with_log([c.title for c in candidates])
    if dup_log:
        log_path = dedup.write_dup_log(dup_log)
        print(f"  observation-log: {len(dup_log)} duplicates → {log_path}")
        # PLAN Phase 2 (C4): try to enrich the existing manifest story with
        # facts from the new source instead of silently dropping it. Mutates
        # `existing` in place; the manifest.save() at end persists it.
        _enrich_from_dups(dup_log, candidates, existing)
    candidates = [candidates[i] for i in keep_idx]
    print(f"After semantic dedup: {len(candidates)}")

    # SIGNIFICANCE FILTER — the real quality gate. Drops trivial, promotional,
    # ordinary, or off-theme stories BEFORE we spend refine + TTS on them.
    # Cheap: one LLM call for the whole batch of titles.
    if candidates:
        print("\nRunning significance filter...")
        verdicts = significance.score_batch(
            {"title": c.title, "source": c.source} for c in candidates
        )
        kept: list[Candidate] = []
        counts = {"IMPORTANT": 0, "INTERESTING": 0, "ORDINARY": 0,
                  "TRIVIAL": 0, "PROMOTIONAL": 0}
        for c, v in zip(candidates, verdicts):
            counts[v] = counts.get(v, 0) + 1
            if v in significance.KEEP:
                kept.append(c)
            else:
                print(f"  DROP [{v:11s}] {c.title[:80]}")
        candidates = kept
        print(f"Verdicts: {counts} → {len(candidates)} kept")

    # Safety cap — only fires if the significance filter kept an unusual
    # amount (misconfigured filter or LLM outage returning all INTERESTING).
    if len(candidates) > config.MAX_NEW_PER_RUN:
        by_source: dict[str, list] = {}
        for c in candidates:
            by_source.setdefault(c.source, []).append(c)
        for src in by_source:
            by_source[src].sort(key=lambda c: c.score, reverse=True)
        picked: list = []
        while len(picked) < config.MAX_NEW_PER_RUN and any(by_source.values()):
            for src in list(by_source.keys()):
                if not by_source[src]:
                    continue
                picked.append(by_source[src].pop(0))
                if len(picked) >= config.MAX_NEW_PER_RUN:
                    break
        candidates = picked
        print(f"Runaway-safety cap: {len(candidates)} across "
              f"{len(set(c.source for c in candidates))} sources.")

    new_stories: list[dict] = []
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")

    for cand in candidates:
        print(f"\n[{cand.source} · {cand.score}] {cand.title[:80]}")

        # Fetch source body — prefer pre-fetched RSS content if long enough
        source_text: str | None = None
        image_url: str | None = None
        if cand.text and len(cand.text.split()) > 120:
            source_text = cand.text
            print("  using pre-fetched text from source")
            if cand.url:
                image_url = extract.image(cand.url)
        elif cand.url:
            print(f"  extracting from {cand.url}")
            source_text = extract.extract(cand.url)
            image_url = extract.image(cand.url)
        if not source_text:
            print("  extraction failed, skipping")
            continue

        print(f"  refining...")
        try:
            refined = refine.refine(cand.title, source_text, cand.id, day)
        except Exception as e:
            print(f"  refine failed: {e}")
            continue
        if not refined:
            print("  refine rejected, skipping")
            continue
        print(f"  refined: {refined.word_count}w · coverage {int(refined.coverage_pct*100)}%")

        if DRY_RUN:
            print("  DRY_RUN: skipping TTS")
            continue

        story = build_story(cand, refined.text, image_url)
        audio_path = config.DATA_DIR / story["audio_path"]
        print(f"  TTS -> {audio_path.name}")
        try:
            stats = tts.synth(refined.text, audio_path, "default")
            story["audio_bytes"] = audio_path.stat().st_size
            story["audio_duration_s"] = round(stats["duration_s"], 1)
            story["tts_chunks"] = stats["chunks_synthed"]
            story["tts_voice"] = stats["voice"]
            print(f"    {stats['chunks_synthed']} chunks, {stats['duration_s']:.1f}s")
        except Exception as e:
            print(f"  TTS failed: {e}")
            continue

        # Whisper round-trip: transcribe the MP3 we just wrote and compare
        # to the input. Cheap on tiny.en (~5s per 90s of audio). If it comes
        # back POOR, log and store the verdict — future work: auto-retry
        # with a slower speed. For now surface it in the manifest so the UI
        # can flag / hide poor audio.
        try:
            val = audio_validate.validate(audio_path, refined.text)
            story["audio_wer"] = val.wer
            story["audio_verdict"] = val.verdict
            story["audio_notes"] = val.notes
            if val.verdict == "poor":
                print(f"    ⚠︎ Whisper verdict POOR (WER {val.wer:.2f}) — {val.notes}")
                if val.mismatched_words:
                    print(f"    ⚠︎ first diffs: {val.mismatched_words[:5]}")
            else:
                print(f"    ✓ Whisper {val.verdict} (WER {val.wer:.2f})")
        except Exception as e:
            print(f"  audio_validate failed: {e}")
            story["audio_verdict"] = "unchecked"

        new_stories.append(story)

    if not new_stories:
        print("\nNo new stories synthesized this run.")
        return 0

    # Batch-classify categories and geolocate all new stories in 2 LLM calls
    print(f"\nCategorizing {len(new_stories)} new stories...")
    try:
        labels = categorize.classify_batch(
            {
                "title": s["title"],
                "domain": s["source_domain"],
                "summary": s.get("summary", ""),
            }
            for s in new_stories
        )
        for s, lbl in zip(new_stories, labels):
            s["main"] = lbl["main"]
            s["sub"] = lbl["sub"]
            # Back-compat mirrors used by existing UI/tests.
            s["category"] = lbl["main"]
            s["subcategory"] = lbl["sub"]
    except Exception as e:
        print(f"  categorization failed: {e}")

    print(f"Geolocating {len(new_stories)} new stories...")
    try:
        locs = geolocate.geolocate_batch(
            {"title": s["title"], "domain": s["source_domain"]} for s in new_stories
        )
        for s, loc in zip(new_stories, locs):
            s["location"] = loc
    except Exception as e:
        print(f"  geolocation failed: {e}")

    merged = sorted(
        new_stories + existing["stories"],
        key=lambda s: s["created_at_ts"],
        reverse=True,
    )[: config.MAX_MANIFEST_STORIES]

    existing["stories"] = merged
    manifest.save(existing)
    manifest.write_rss(existing)
    print(f"\nAdded {len(new_stories)} stories. Manifest holds {len(merged)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
