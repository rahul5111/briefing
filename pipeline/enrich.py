"""Cross-source enrichment (PLAN Phase 2: C2 + C3).

When a new candidate story is a semantic duplicate of a story already in
the manifest, we don't want to just drop it — the new source may add
facts, quotes, or a corrective angle the existing summary misses.

Pipeline:
    detect_delta(existing_summary, new_article_text)
        → { adds_material: bool, delta_pct: float, new_facts: [str] }

    if adds_material:
        neutral_synthesize(existing_story, new_article_text, new_facts)
            → { summary: str, key_points: [str] }

The synthesized summary is TTS-ready (spoken-cadence conventions from
refine.py already apply — this is the same audience). Callers merge it
into the manifest and re-run TTS.

Cost model per detected duplicate:
    - 1 cheap LLM call (delta detection) always
    - 1 mid-weight LLM call (synthesis) only when adds_material=True
    - 1 TTS run only when synthesis fires
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import TypedDict

from google import genai

from . import config


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


# Threshold above which we consider the new source materially additive.
# Kept low so we err on merging; the audio budget is bounded by cron cadence.
DELTA_THRESHOLD_PCT = 15.0


class DeltaResult(TypedDict):
    adds_material: bool
    delta_pct: float
    new_facts: list[str]
    reason: str


class SynthResult(TypedDict):
    summary: str
    key_points: list[str]


_DELTA_PROMPT = """You are comparing a NEW article to an EXISTING summary of the same story.

Task: identify what NEW factual information the new article adds beyond the existing summary.

- List each new fact (numbers, names, quotes, sources, corrections, opposing views) as a short bullet.
- Ignore stylistic differences and repetition of facts already in the summary.
- Estimate what percentage of the new article's substance is NOT in the existing summary (0-100). Use only concrete facts, not opinions.
- Do not invent facts not in the new article.

Return ONE JSON object with no code fences, exactly:
  {{"delta_pct": <number>, "new_facts": ["<short bullet>", ...], "reason": "<one-sentence rationale>"}}

EXISTING SUMMARY:
{existing_summary}

NEW ARTICLE (may be truncated):
{new_article}
"""


_SYNTH_PROMPT = """Rewrite the summary of this story as a neutral, bias-balanced version using facts from BOTH sources.

Rules:
- Same length as the existing summary (150-360 words).
- Do not introduce facts that are not in either source.
- Preserve the strongest concrete facts from both.
- Reconcile any factual conflict by attributing to the source that reported it (e.g., "Reuters reports X, while the BBC characterises it as Y").
- Spoken cadence: numbers spelled out for TTS (e.g., "thirty million dollars" not "$30m"), acronyms letter-spaced with spaces (e.g., "N B A"), short sentences.
- Neutral tone. No editorialising.
- Include the top 5-8 must-include facts as a list AFTER the summary text.

Return ONE JSON object with no code fences, exactly:
  {{"summary": "<merged summary text>", "key_points": ["<fact>", ...]}}

EXISTING SUMMARY:
{existing_summary}

EXISTING KEY POINTS:
{existing_points}

NEW ARTICLE (may be truncated):
{new_article}

NEW FACTS IDENTIFIED (from delta detection):
{new_facts}
"""


def _parse_json_object(raw: str) -> dict | None:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def detect_delta(existing_summary: str, new_article_text: str) -> DeltaResult:
    """Return whether the new article adds materially new information.

    Falls back safely (adds_material=False) on any parse or API error so
    the caller can drop-as-before rather than crash.
    """
    if not existing_summary or not new_article_text:
        return {"adds_material": False, "delta_pct": 0.0, "new_facts": [], "reason": "empty input"}
    client = _get_client()
    try:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=_DELTA_PROMPT.format(
                existing_summary=existing_summary[:3000],
                new_article=new_article_text[:6000],
            ),
            config={"temperature": 0.0, "max_output_tokens": 700},
        )
    except Exception as e:
        return {"adds_material": False, "delta_pct": 0.0, "new_facts": [], "reason": f"api error: {e}"}
    parsed = _parse_json_object(resp.text or "")
    if not parsed:
        return {"adds_material": False, "delta_pct": 0.0, "new_facts": [], "reason": "parse failure"}
    try:
        pct = float(parsed.get("delta_pct", 0))
    except (TypeError, ValueError):
        pct = 0.0
    facts = parsed.get("new_facts", []) or []
    if not isinstance(facts, list):
        facts = []
    facts = [str(f).strip() for f in facts if str(f).strip()]
    return {
        "adds_material": pct >= DELTA_THRESHOLD_PCT and len(facts) > 0,
        "delta_pct": round(pct, 1),
        "new_facts": facts,
        "reason": str(parsed.get("reason", "")).strip(),
    }


def neutral_synthesize(
    existing_summary: str,
    existing_key_points: list[str] | None,
    new_article_text: str,
    new_facts: list[str],
) -> SynthResult | None:
    """Return a merged bias-balanced summary + key points.

    Returns None on failure so the caller can leave the existing story
    untouched (never worse than the pre-enrich state).
    """
    client = _get_client()
    try:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=_SYNTH_PROMPT.format(
                existing_summary=existing_summary[:4000],
                existing_points="\n".join(f"- {p}" for p in (existing_key_points or [])),
                new_article=new_article_text[:8000],
                new_facts="\n".join(f"- {f}" for f in new_facts),
            ),
            config={"temperature": 0.2, "max_output_tokens": 2000},
        )
    except Exception:
        return None
    parsed = _parse_json_object(resp.text or "")
    if not parsed:
        return None
    summary = str(parsed.get("summary", "")).strip()
    if not summary:
        return None
    pts = parsed.get("key_points", []) or []
    if not isinstance(pts, list):
        pts = []
    pts = [str(p).strip() for p in pts if str(p).strip()]
    return {"summary": summary, "key_points": pts}
