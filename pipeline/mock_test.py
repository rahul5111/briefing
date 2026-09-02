"""Mock validation harness: pick N real HN stories, run the full refinement +
TTS pipeline, then generate a side-by-side report showing:

  - Source article word count and key points
  - Draft summary
  - Final normalized text that TTS consumes
  - Coverage % of key points in final text
  - Whisper round-trip transcript
  - WER, CER, silence structure, verdict

Usage:  python -m pipeline.mock_test [story_ids...]
        python -m pipeline.mock_test              # uses 3 default fresh HN stories
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config, extract, refine, tts, audio_validate, fetch


DEFAULT_IDS = ["hn-49537553", "hn-49535526", "hn-49526069"]

REPORT_DIR = config.DATA_DIR / "reviews" / "_mock_reports"


def _load_story(story_id: str) -> dict | None:
    if not config.MANIFEST_PATH.exists():
        return None
    data = json.loads(config.MANIFEST_PATH.read_text())
    return next((s for s in data.get("stories", []) if s["id"] == story_id), None)


def _run(story: dict) -> dict:
    story_id = story["id"]
    print(f"\n╔══ {story_id}: {story['title'][:70]}")
    print(f"╚══ url: {story.get('source_url')}")

    url = story.get("source_url")
    source = extract.extract(url) if url else None
    if not source:
        source = story.get("summary", "") or ""
    print(f"    source: {len(source.split())} words")

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = refine.refine(story["title"], source, f"{story_id}-mock", day)
    if not r:
        print("    refine FAILED")
        return {"story_id": story_id, "status": "refine_failed"}

    print(f"    refined: {r.word_count}w · coverage {int(r.coverage_pct*100)}%")
    print(f"    passes:  {' → '.join(r.passes_used)}")
    if r.missing_points:
        print(f"    MISSING: {'; '.join(r.missing_points)}")

    audio_path = Path(f"/tmp/{story_id}-mock.mp3")
    stats = tts.synth(r.text, audio_path, story.get("category", "tech"))
    print(f"    tts: {stats['chunks_synthed']} chunks, {stats['duration_s']:.1f}s")

    print("    validating audio via whisper round-trip...")
    val = audio_validate.validate(audio_path, r.text)
    print(f"    → verdict={val.verdict.upper()} | wer={val.wer} · cer={val.cer}")
    print(f"    → silence: {val.silence.sentence_gaps} sentence gaps, "
          f"{val.silence.paragraph_gaps} paragraph gaps, "
          f"{val.silence.suspicious_gaps} suspicious")
    if val.notes:
        for n in val.notes:
            print(f"    → note: {n}")
    if val.mismatched_words:
        print(f"    → first mismatches:")
        for a, b in val.mismatched_words[:6]:
            print(f"       '{a}' → heard as '{b}'")

    return {
        "story_id": story_id,
        "title": story["title"],
        "url": url,
        "source_words": len(source.split()),
        "source_snippet": source[:400],
        "key_points": r.key_points,
        "final_text": r.text,
        "word_count": r.word_count,
        "coverage_pct": r.coverage_pct,
        "missing_points": r.missing_points,
        "audio_path": str(audio_path),
        "tts_chunks": stats["chunks_synthed"],
        "duration_s": stats["duration_s"],
        "whisper_transcript": val.transcript,
        "wer": val.wer,
        "cer": val.cer,
        "silence": val.silence.__dict__,
        "verdict": val.verdict,
        "notes": val.notes,
        "mismatched_words": val.mismatched_words[:12],
        "passes_used": r.passes_used,
        "sanity_notes": r.sanity_notes,
    }


def _write_report(results: list[dict]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    md = REPORT_DIR / f"mock-{ts}.md"

    lines = [
        f"# Mock validation report",
        f"_generated {datetime.now(timezone.utc).isoformat()}_",
        "",
        "## Summary",
        "",
        "| Story | Src→Out words | Coverage | Duration | WER | CER | Verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.get("status") == "refine_failed":
            lines.append(f"| {r['story_id']} | — | — | — | — | — | REFINE_FAILED |")
            continue
        lines.append(
            f"| {r['story_id']} | {r['source_words']}→{r['word_count']} | "
            f"{int(r['coverage_pct']*100)}% | {r['duration_s']:.1f}s | "
            f"{r['wer']} | {r['cer']} | **{r['verdict'].upper()}** |"
        )
    lines.append("")

    for r in results:
        if r.get("status") == "refine_failed":
            continue
        lines += [
            "---",
            f"## {r['story_id']}: {r['title']}",
            f"[{r['url']}]({r['url']})",
            "",
            f"**Passes:** `{' → '.join(r['passes_used'])}`  ",
            f"**Coverage:** {int(r['coverage_pct']*100)}% "
            f"({len(r['key_points']) - len(r['missing_points'])}/{len(r['key_points'])} key points)  ",
            f"**Audio:** `{r['audio_path']}` — {r['duration_s']:.1f}s, "
            f"{r['tts_chunks']} chunks, {r['silence']['sentence_gaps']} sentence gaps, "
            f"{r['silence']['paragraph_gaps']} paragraph gaps, "
            f"{r['silence']['suspicious_gaps']} suspicious gaps  ",
            f"**Audio verdict:** **{r['verdict'].upper()}** (WER {r['wer']}, CER {r['cer']})",
            "",
            "### Key points extracted from source",
        ]
        for i, kp in enumerate(r["key_points"], 1):
            missing = " **← MISSING**" if kp in r["missing_points"] else ""
            lines.append(f"{i}. {kp}{missing}")
        lines += [
            "",
            "### Source snippet (first 400 chars)",
            "```",
            r["source_snippet"],
            "```",
            "",
            "### Final text that TTS consumed",
            "> " + r["final_text"].replace("\n\n", "\n>\n> "),
            "",
            "### What Whisper heard back",
            "> " + r["whisper_transcript"].replace("\n", "\n> "),
            "",
        ]
        if r["mismatched_words"]:
            lines.append("### First mismatches (input → heard)")
            for a, b in r["mismatched_words"]:
                lines.append(f"- `{a}` → `{b}`")
            lines.append("")
        if r["notes"]:
            lines.append("### Notes")
            for n in r["notes"]:
                lines.append(f"- {n}")
            lines.append("")

    md.write_text("\n".join(lines))
    return md


def main(story_ids: list[str]) -> int:
    if not story_ids:
        story_ids = DEFAULT_IDS
    results: list[dict] = []
    for sid in story_ids:
        story = _load_story(sid)
        if not story:
            print(f"⚠ story {sid} not in manifest, skipping")
            continue
        try:
            results.append(_run(story))
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({"story_id": sid, "status": "error", "error": str(e)})

    if not results:
        print("no results to report")
        return 1

    report_path = _write_report(results)
    print(f"\n══════════════════════════════════════════")
    print(f"Wrote report: {report_path}")
    print(f"══════════════════════════════════════════")
    # print concise summary
    print(f"\n{'Story':<20} {'Cov':<6} {'Dur':<8} {'WER':<6} {'Verdict':<10}")
    for r in results:
        if r.get("status") in ("error", "refine_failed"):
            print(f"{r['story_id']:<20} FAILED")
            continue
        print(f"{r['story_id']:<20} {int(r['coverage_pct']*100)}%{'':<3} "
              f"{r['duration_s']:.1f}s{'':<2} {r['wer']:<6} {r['verdict']:<10}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
