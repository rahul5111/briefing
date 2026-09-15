"""B-81 / B-109 Video-understanding provider abstraction.

Per docs/design-review-youtube-integration.md §3. The provider interface
takes a YouTube URL + a task-shaped prompt and returns structured event
extraction. The current concrete impl is Gemini video URL analysis; the
abstraction lets us swap to YouTube Transcript API + a separate LLM
without touching stages E/F if Google changes Gemini video pricing or
quotas.

Prompt policy (matches user directive 2026-09-14):
  "we donot need any deep dive - we only need the transcript analysis
   to either create the news article or to enhance the existing one"

So the prompt is transcript-focused: extract discrete events with
attribution, dates, and numbers — NOT a deep expert analysis.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Protocol

from google import genai

from . import config


@dataclass
class ExtractedEvent:
    """One event extracted from a video. Matches design §9 schema."""
    title: str = ""
    who: str = ""
    what: str = ""
    when: str = ""              # ISO date if present, else free text
    where: str = ""
    numbers: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    approx_timestamps: list[str] = field(default_factory=list)  # "MM:SS"
    predicted_significance: float = 0.0
    predicted_category: str = ""
    one_line_summary: str = ""


@dataclass
class VideoAnalysis:
    """Result of analyzing one video via the provider."""
    video_id: str
    events: list[ExtractedEvent] = field(default_factory=list)
    provider: str = ""
    tokens_used: int = 0
    error: str = ""


class VideoUnderstandingProvider(Protocol):
    """Any concrete provider implements this."""
    name: str

    def analyze(self, video_url: str, video_id: str,
                context: dict | None = None) -> VideoAnalysis:
        ...


TRANSCRIPT_ANALYSIS_PROMPT = """You are extracting discrete news events from a
YouTube video transcript. Focus on what is spoken; do not speculate about
production quality or channel bias.

For each distinct event mentioned, return one JSON object with:
  title              — a short factual title (no adjectives, no clickbait)
  who                — named institution or person taking action
  what               — what they did or announced (verb + object)
  when               — ISO date if stated, else best free-text approximation
  where              — geographic scope if stated
  numbers            — array of specific numbers/amounts mentioned
  quotes             — array of ≤120-char direct quotes (only if useful)
  approx_timestamps  — array of MM:SS positions where this event is discussed
  predicted_significance — 0.0 to 1.0 (your best guess before our filter runs)
  predicted_category — one of: AI, Tech, Science, Sports, US, India, World, Business
  one_line_summary   — <=140 chars, single sentence, no adjectives

Rules:
- Only include events with a named institution and a specific action.
- Skip general commentary, opinion, and exam-prep framing.
- If the video is a recap covering N events, return N separate objects.
- Prefer under-extraction to over-extraction. Return [] if nothing qualifies.

Return a JSON array (no prose, no code fences).
"""


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


class GeminiVideoProvider:
    """Concrete provider: Gemini URL analysis with the transcript-focused prompt."""

    name = "gemini-video-url"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("GEMINI_VIDEO_MODEL", config.GEMINI_MODEL)

    def analyze(self, video_url: str, video_id: str,
                context: dict | None = None) -> VideoAnalysis:
        client = _get_client()
        try:
            resp = client.models.generate_content(
                model=self.model,
                contents=[
                    {"role": "user", "parts": [
                        {"text": TRANSCRIPT_ANALYSIS_PROMPT},
                        {"file_data": {"file_uri": video_url}},
                    ]},
                ],
                config={"temperature": 0.0, "max_output_tokens": 4000},
            )
            raw = (resp.text or "").strip()
        except Exception as e:
            return VideoAnalysis(video_id=video_id, provider=self.name,
                                 error=f"{type(e).__name__}: {e}")
        try:
            # Strip fences if the model wrapped output.
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.rsplit("```", 1)[0]
            arr = json.loads(raw)
        except Exception as e:
            return VideoAnalysis(video_id=video_id, provider=self.name,
                                 error=f"parse: {type(e).__name__}: {e}")
        events: list[ExtractedEvent] = []
        for x in arr if isinstance(arr, list) else []:
            if not isinstance(x, dict):
                continue
            events.append(ExtractedEvent(
                title=str(x.get("title", "")).strip(),
                who=str(x.get("who", "")).strip(),
                what=str(x.get("what", "")).strip(),
                when=str(x.get("when", "")).strip(),
                where=str(x.get("where", "")).strip(),
                numbers=[str(n) for n in (x.get("numbers") or [])],
                quotes=[str(q)[:120] for q in (x.get("quotes") or [])],
                approx_timestamps=[str(t) for t in (x.get("approx_timestamps") or [])],
                predicted_significance=float(x.get("predicted_significance", 0.0) or 0.0),
                predicted_category=str(x.get("predicted_category", "")).strip(),
                one_line_summary=str(x.get("one_line_summary", "")).strip()[:200],
            ))
        return VideoAnalysis(video_id=video_id, events=events, provider=self.name)


def default_provider() -> VideoUnderstandingProvider:
    return GeminiVideoProvider()
