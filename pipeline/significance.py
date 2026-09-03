"""Significance filter — drops trivial, promotional, or off-theme stories
before they hit the expensive refine + TTS steps.

The upstream ingestion is deliberately broad — we pull from many sources with
low thresholds so nothing important is missed. This module is the quality
gate that removes noise before we spend LLM + TTS budget on it.

Verdicts (per story):
  IMPORTANT   — hard news, substantive analysis, meaningful launch: KEEP
  INTERESTING — non-critical but worth listening to: KEEP
  ORDINARY    — a routine update most readers can skip: DROP by default
  TRIVIAL     — clickbait, listicles, throat-clearing, self-promo: DROP
  PROMOTIONAL — a product pitch dressed as news: DROP
"""
from __future__ import annotations
import json
import re
from typing import Iterable, Literal
from google import genai

from . import config


Verdict = Literal["IMPORTANT", "INTERESTING", "ORDINARY", "TRIVIAL", "PROMOTIONAL"]
KEEP = {"IMPORTANT", "INTERESTING"}

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


PROMPT = """You are the editor of a daily audio news briefing. Score each
candidate story below on whether it belongs in the show.

A listener has ~10 minutes total per session. They already read tech Twitter
and know about big launches. They want:
  - Real news: policy, incidents, releases with substance, court rulings,
    scientific findings, geopolitics, security breaches, market moves.
  - Non-obvious analysis they would not have thought about themselves.
  - Stories with a concrete "what happened, what changes now" arc.

They do NOT want:
  - Clickbait ("You won't believe...", "10 reasons...")
  - Reposts of press releases
  - Personal blog posts with no news content
  - Listicles or roundups
  - Speculation dressed as reporting
  - Product marketing with no independent reporting
  - Repeats of stories they already know

For each story, return one of these verdicts:
  IMPORTANT   — hard news or substantive analysis; keep
  INTERESTING — non-critical but genuinely worth 90 seconds; keep
  ORDINARY    — a real update but not really newsworthy; drop
  TRIVIAL     — clickbait, listicle, throat-clearing; drop
  PROMOTIONAL — a product pitch dressed as news; drop

Return a JSON array of the same length in the same order. Just the array.
Example: ["IMPORTANT", "TRIVIAL", "INTERESTING", ...]

Stories:
{list}
"""


def _extract_json(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    m = re.search(r"\[.*\]", s, re.S)
    return m.group(0) if m else s


def score_batch(items: Iterable[dict]) -> list[Verdict]:
    """Return one verdict per story in the same order. Falls back to
    INTERESTING on error so nothing is silently dropped when the LLM fails."""
    items = list(items)
    if not items:
        return []
    lines = [f"{i+1}. [{it.get('source','')}] {it['title']}"
             for i, it in enumerate(items)]
    prompt = PROMPT.format(list="\n".join(lines))
    client = _get_client()
    try:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 800},
        )
        raw = (resp.text or "").strip()
        arr = json.loads(_extract_json(raw))
    except Exception:
        return ["INTERESTING"] * len(items)
    out: list[Verdict] = []
    for x in arr:
        v = str(x).strip().upper()
        if v in ("IMPORTANT", "INTERESTING", "ORDINARY", "TRIVIAL", "PROMOTIONAL"):
            out.append(v)  # type: ignore
        else:
            out.append("INTERESTING")
    while len(out) < len(items):
        out.append("INTERESTING")
    return out[: len(items)]
