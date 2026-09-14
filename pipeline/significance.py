"""Significance filter — drops trivial, promotional, or off-theme stories
before they hit the expensive refine + TTS steps.

Two filters live here:

v1 (legacy) — `score_batch`: coarse IMPORTANT/INTERESTING/ORDINARY/TRIVIAL/
              PROMOTIONAL verdict per title. Kept because tests still call
              it and because it's cheap enough to run as a first pass.

v2 (new)    — `score_v2_batch`: GKToday-reverse-engineered strict filter,
              tuned for the Priya persona (see docs/tracks-abc-plan.md).
              Emits a numeric score plus band, plus which ACCEPT / REJECT
              rules fired plus which TIGHTER-THAN-GKTODAY overrides
              downgraded the score. Only "accept" band passes to refine +
              TTS. Rejections are logged to data/rejections/YYYY-MM-DD.jsonl
              so a human can audit false-negatives.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
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


# ── v1 (legacy, kept for tests) ──────────────────────────────────────

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


def _extract_json_array_of_objects(raw: str) -> str:
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


# ── v2 (strict, GKToday-standard filter) ─────────────────────────────

Band = Literal["accept", "borderline", "reject"]


@dataclass
class SignificanceV2:
    score: float                        # 0.0-1.0
    band: Band                          # accept / borderline / reject
    accept_hits: list[str] = field(default_factory=list)      # A1-A10
    reject_hits: list[str] = field(default_factory=list)      # R1-R14
    tighter_penalties: list[str] = field(default_factory=list)  # T1-T3
    one_line_reason: str = ""


PROMPT_V2 = """You are a strict news-desk editor filtering stories for Priya,
a Bengaluru product manager who reads news for professional edge, civic
literacy, and personal joy. Score each story from 0.0 to 1.0 on
"significance_v2".

ACCEPT band (score >= 0.65) requires ALL of:
  A1  A named institution took a specific action, or a measurable event
      occurred with concrete numbers/names/dates.
  A2  Story has second-order consequences: rule change, market impact,
      legal precedent, capability unlock, or budgetary commitment.
  A3  Reducible to <who> <did what> <to whom> <with what outcome> in one
      sentence without adjectives.
  A4  Scope >= state level (India) or >= national level (foreign).
  A5  Updates the reader's model of the world, not merely entertains.
  A6  Verifiable via a primary source (gazette, filing, court order, paper,
      release).
  A7  If sports: national record, major-tournament result, or career
      milestone in an in-season major (IPL, F1, badminton BWF, tennis
      Slam, ICC event, Grand Slam).
  A8  If sci-tech: demonstrated result, not roadmap/intent.
  A9  If business: regulator action, closed M&A, IPO, or sector-wide
      policy — not a price move alone.
  A10 If international: India is a party, OR head-of-state / conflict /
      treaty / election-result level.

HARD-REJECT (score <= 0.15) if ANY of:
  R1  Ceremonial (greetings, felicitations, foundation stones, photo-ops).
  R2  Individual crime (road rage, hit-and-run, domestic violence) with
      no precedent and no public official involved.
  R3  Celebrity personal life (relationships, homes, quotes, apparel).
  R4  Human-interest feel-good with no policy hook (viral kid, viral
      animal, viral rescue).
  R5  Corporate PR / product launch / hiring-firing without regulator or
      sector-wide pattern.
  R6  Listicles, "5 ways to…", shopping guides, gadget round-ups.
  R7  Weather forecast (unless declared disaster with casualties/
      evacuations).
  R8  Opinion, commentary, "decoding X" analyses, editorial.
  R9  Micro-procedural mishap without regulator follow-up (one flight
      delayed, one visa slip).
  R10 Stock/crypto price move without a triggering policy/earnings event.
  R11 Rumor, unconfirmed leaks, "sources say," poll-tracker speculation.
  R12 Sub-state civic trivia (one ward election, one MLA statement).
  R13 Off-season / non-major sports; non-national records.
  R14 Sub-national award below Padma / national-honour tier.

TIGHTER-THAN-GKTODAY overrides (apply AFTER placing in accept band; each
downgrades the score):
  T1  Actionability: -0.2 if institutional but no downstream effect on a
      Bengaluru PM's decisions, beliefs, or civic understanding this week.
  T2  Novelty: -0.2 if this is the Nth routine instance of a known pattern
      (recurring exercise, another MoU, another delegation visit).
  T3  Substance-over-signaling: -0.3 for MoUs, LoIs, aspirational bilateral
      targets, or "target set at X by 2030" statements without a binding
      instrument or measurable deliverable within 24 months.

For EACH story below, return one JSON object exactly like:
  {{"score": 0.72, "band": "accept",
    "accept_hits": ["A1","A2","A4","A6"],
    "reject_hits": [],
    "tighter_penalties": [],
    "one_line_reason": "<=140 chars"}}

Return a JSON array of these objects, one per story, in the same order.
No prose, no code fences.

Stories:
{list}
"""


def _valid_v2(obj) -> SignificanceV2 | None:
    if not isinstance(obj, dict):
        return None
    try:
        score = float(obj.get("score", 0.0))
    except (TypeError, ValueError):
        return None
    score = max(0.0, min(1.0, score))
    band = str(obj.get("band", "")).strip().lower()
    if band not in ("accept", "borderline", "reject"):
        # Derive band from score if the LLM forgot to set one.
        if score >= 0.65:
            band = "accept"
        elif score >= 0.35:
            band = "borderline"
        else:
            band = "reject"
    return SignificanceV2(
        score=round(score, 3),
        band=band,  # type: ignore
        accept_hits=[str(x) for x in (obj.get("accept_hits") or []) if str(x).strip()],
        reject_hits=[str(x) for x in (obj.get("reject_hits") or []) if str(x).strip()],
        tighter_penalties=[str(x) for x in (obj.get("tighter_penalties") or []) if str(x).strip()],
        one_line_reason=str(obj.get("one_line_reason", "")).strip()[:200],
    )


_FALLBACK_V2 = SignificanceV2(
    score=0.55, band="borderline",
    one_line_reason="fallback: LLM error or parse failure",
)


def score_v2_batch(items: Iterable[dict]) -> list[SignificanceV2]:
    """Return one SignificanceV2 per item in the same order.

    Each item: {"title": str, "summary": str, "source": str, "category": str}.
    On any API/parse failure, returns borderline defaults so the pipeline
    doesn't hard-drop everything when Gemini hiccups.
    """
    items = list(items)
    if not items:
        return []
    lines = []
    for i, it in enumerate(items, 1):
        summary = (it.get("summary") or "")[:220]
        lines.append(
            f"{i}. title: {it.get('title','').strip()}\n"
            f"   source: {it.get('source','')}\n"
            f"   category: {it.get('category','')}\n"
            f"   summary: {summary}"
        )
    prompt = PROMPT_V2.format(list="\n\n".join(lines))
    client = _get_client()
    try:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 200 * len(items) + 400},
        )
        raw = (resp.text or "").strip()
        arr = json.loads(_extract_json_array_of_objects(raw))
    except Exception:
        return [_FALLBACK_V2] * len(items)
    out: list[SignificanceV2] = []
    for x in arr:
        out.append(_valid_v2(x) or _FALLBACK_V2)
    while len(out) < len(items):
        out.append(_FALLBACK_V2)
    return out[: len(items)]


def write_rejection_log(rejections: list[dict]) -> Path | None:
    """Append rejection records to data/rejections/YYYY-MM-DD.jsonl for
    later audit. Each record: story identity + verdict + reason.
    """
    if not rejections:
        return None
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_dir = config.ROOT / "data" / "rejections"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{day}.jsonl"
    run_ts = datetime.now(timezone.utc).isoformat()
    with path.open("a") as f:
        for r in rejections:
            r = dict(r)
            r.setdefault("run_ts", run_ts)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path
