"""B-81 / B-109 YouTube secondary-explainer pipeline.

Scaffold implementing stages A-F from
docs/design-review-youtube-integration.md §2. Each stage is a pure
function whose input/output boundaries match the design so they can be
unit-tested independently.

This module is NOT wired into `pipeline/run.py` yet — it needs a
YOUTUBE_API_KEY secret and channel entries flipped to `enabled: true` in
`youtube_sources.yaml` first. Both are gated on the shadow-eval week
per §4.

Stages:
  A. FETCH             — list recent videos via YouTube Data API v3.
  B. CLASSIFY          — cheap Gemini call to tag video_type / topic.
  C. PARSE             — regex over description + chapters (no LLM).
  D. MATCH             — semantic-match against recent Briefing stories.
  E. DEEP_ANALYZE      — Gemini video URL analysis for NEW_POTENTIAL_EVENT.
  F. ENRICH_OR_EMIT    — attach delta to existing story, or emit new candidate.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

import yaml

from . import config
from .video_understanding import (
    ExtractedEvent, VideoAnalysis, default_provider,
)


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).parent / "youtube_sources.yaml"
SEEN_STATE_PATH = ROOT / "data" / "state" / "youtube_seen.jsonl"
AUDIT_DIR = ROOT / "data" / "audits"


VideoType = str  # DAILY_CURRENT_AFFAIRS | WEEKLY_RECAP | MONTHLY_RECAP |
                 # COURSE_PROMOTION | LIVE_STREAM | SHORT | OTHER


@dataclass
class YouTubeVideo:
    id: str
    channel: str
    title: str
    description: str
    published_at: str
    duration_s: int
    url: str
    channel_role: list[str] = field(default_factory=list)
    video_type: VideoType = ""
    chapters: list[tuple[str, str]] = field(default_factory=list)  # (timestamp, label)


# ── Stage A. FETCH ────────────────────────────────────────────────────

def load_channel_config() -> list[dict]:
    """Return the list of enabled channel configs from youtube_sources.yaml."""
    if not CONFIG_PATH.exists():
        return []
    doc = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    return [c for c in (doc.get("youtube_sources") or []) if c.get("enabled")]


def fetch_recent_videos(channel: dict) -> list[YouTubeVideo]:
    """Stage A — list recent videos for a channel via YouTube Data API v3.

    Requires YOUTUBE_API_KEY. Returns [] if the API key is absent so
    downstream stages no-op cleanly.
    """
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return []
    # TODO(B-109 impl phase): googleapiclient.discovery.build("youtube","v3",
    # developerKey=key). See design doc §6.1 for the Search+Videos flow.
    # Left unimplemented to keep the scaffold callable without paid state.
    return []


# ── Stage B. CLASSIFY ─────────────────────────────────────────────────

_TYPE_HINTS: dict[VideoType, list[str]] = {
    "SHORT": [r"#shorts?\b"],
    "LIVE_STREAM": [r"\blive\b", r"\bstreaming\b"],
    "COURSE_PROMOTION": [r"\bbatch\b", r"\bcourse\b", r"\benrol", r"\bfree class\b"],
    "MONTHLY_RECAP": [r"\bmonthly (?:recap|round|highlights)\b"],
    "WEEKLY_RECAP": [r"\bweekly (?:recap|round|highlights)\b"],
    "DAILY_CURRENT_AFFAIRS": [r"\bdaily current affairs\b", r"\bnews today\b"],
}


def classify_video_type(video: YouTubeVideo) -> VideoType:
    """Stage B — heuristic type-tag from title + description.

    Cheap regex prefilter. Design §6.2 spec upgrades this to a Gemini
    call with structured output — deferred to the impl phase; the
    heuristic classifier lets the rest of the scaffold run without
    additional Gemini load during shadow eval.
    """
    text = f"{video.title}\n{video.description}".lower()
    if video.duration_s > 0 and video.duration_s < 60:
        return "SHORT"
    for vtype, patterns in _TYPE_HINTS.items():
        if any(re.search(p, text) for p in patterns):
            return vtype
    return "OTHER"


# ── Stage C. PARSE (chapters + description) ───────────────────────────

_CHAPTER_LINE = re.compile(
    r"^\s*(?:\(?)?(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\)?\s*[-–—:]?\s*(?P<label>.+?)\s*$"
)


def parse_chapters(description: str) -> list[tuple[str, str]]:
    """Stage C — extract [(timestamp, label), …] from a YouTube description.

    Reference: design §7.
    """
    out: list[tuple[str, str]] = []
    for line in (description or "").splitlines():
        m = _CHAPTER_LINE.match(line)
        if m and len(m.group("label")) <= 120:
            out.append((m.group("ts"), m.group("label").strip()))
    return out


# ── Stage D. MATCH (semantic vs recent stories) ───────────────────────

def match_against_recent_stories(video: YouTubeVideo,
                                 recent_stories: list[dict],
                                 topk: int = 5) -> list[tuple[dict, float]]:
    """Stage D — match a video against recent Briefing stories.

    Returns [(story, similarity), …] sorted by similarity desc. Empty
    list means the video appears to be a NEW event we haven't covered.

    Impl uses the sentence-transformers embedding already loaded by the
    rest of the pipeline; deferred to the impl phase to avoid pulling
    the model in when only running the scaffold.
    """
    # TODO(B-109 impl phase): reuse pipeline.dedup embedder to compute
    # cosine similarity between video.title+description and each recent
    # story's headline+summary. Return topk pairs with sim >= 0.55.
    _ = video, recent_stories, topk
    return []


# ── Stage E. DEEP ANALYZE (Gemini video URL) ──────────────────────────

def deep_analyze(video: YouTubeVideo) -> VideoAnalysis:
    """Stage E — Gemini video URL analysis, transcript-focused prompt.

    Only called for videos flagged as NEW_POTENTIAL_EVENT by stage D
    AND above the deep-analyze significance threshold. Every call is
    counted against `max_deep_analysis_per_run` in youtube_sources.yaml.
    """
    provider = default_provider()
    return provider.analyze(video.url, video.id,
                            context={"channel": video.channel,
                                     "title": video.title})


# ── Stage F. ENRICH_OR_EMIT ───────────────────────────────────────────

@dataclass
class EnrichmentAction:
    """Result of stage F — either 'enrich' an existing story or 'emit' a new one."""
    kind: str                    # "enrich" | "emit" | "skip"
    story_id: str = ""           # target for enrich; new id for emit
    events: list[ExtractedEvent] = field(default_factory=list)
    reason: str = ""


def decide_enrichment(video: YouTubeVideo,
                      analysis: VideoAnalysis,
                      matched_stories: list[tuple[dict, float]]) -> EnrichmentAction:
    """Stage F — decide whether to enrich a matched story or emit a new one.

    Design §11: if a matched story exists with sim>=0.65, ENRICH; if
    only a weaker match, and events have predicted_significance>=0.55,
    EMIT; else SKIP.
    """
    if analysis.error:
        return EnrichmentAction(kind="skip", reason=f"analyze_error: {analysis.error}")
    if not analysis.events:
        return EnrichmentAction(kind="skip", reason="no_events")
    if matched_stories:
        top_story, top_sim = matched_stories[0]
        if top_sim >= 0.65:
            return EnrichmentAction(kind="enrich",
                                    story_id=str(top_story.get("id", "")),
                                    events=analysis.events,
                                    reason=f"matched_sim={top_sim:.2f}")
    high_sig = [e for e in analysis.events if e.predicted_significance >= 0.55]
    if high_sig:
        return EnrichmentAction(kind="emit", events=high_sig,
                                reason="new_event_predicted")
    return EnrichmentAction(kind="skip", reason="below_significance")


# ── Seen-state helpers ────────────────────────────────────────────────

def load_seen_ids() -> set[str]:
    """Read data/state/youtube_seen.jsonl → set of video ids."""
    if not SEEN_STATE_PATH.exists():
        return set()
    ids: set[str] = set()
    for line in SEEN_STATE_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ids.add(json.loads(line)["video_id"])
        except Exception:
            continue
    return ids


def mark_seen(video: YouTubeVideo, action: EnrichmentAction) -> None:
    """Append one seen-state record. Design §5.2."""
    SEEN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "video_id": video.id,
        "channel": video.channel,
        "title": video.title,
        "video_type": video.video_type,
        "action": action.kind,
        "seen_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    with SEEN_STATE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Entry point ───────────────────────────────────────────────────────

def run_once(recent_stories: list[dict] | None = None) -> dict:
    """Run all stages for every enabled channel.

    Called from `pipeline/run.py` once wired in (B-109 impl phase).
    Returns a summary dict for the health dashboard.
    """
    recent_stories = recent_stories or []
    seen = load_seen_ids()
    channels = load_channel_config()
    summary = {"channels": len(channels), "videos_seen": 0,
               "enriched": 0, "emitted": 0, "skipped": 0}
    for ch in channels:
        for video in fetch_recent_videos(ch):
            if video.id in seen:
                continue
            summary["videos_seen"] += 1
            video.video_type = classify_video_type(video)
            video.chapters = parse_chapters(video.description)
            matches = match_against_recent_stories(video, recent_stories)
            # Deep analyze only when we don't have a strong match.
            if matches and matches[0][1] >= 0.85:
                analysis = VideoAnalysis(video_id=video.id, provider="skipped-strong-match")
            else:
                analysis = deep_analyze(video)
            action = decide_enrichment(video, analysis, matches)
            mark_seen(video, action)
            summary[action.kind if action.kind in summary else "skipped"] += 1
    return summary


if __name__ == "__main__":
    print(json.dumps(run_once(), indent=2))
