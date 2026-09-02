"""Extract must-include facts from a source article, and verify they survive
each refinement pass. This is the coverage gate — a briefing is worthless if
it drops the number, party, or timeline the reader actually needs.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from google import genai

from . import config


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


DISTILL_PROMPT = """You are extracting the MUST-INCLUDE facts from a news
article. These are the facts a reader would consider the story incomplete
without.

Return exactly 5 to 8 facts as a JSON array of strings. Each fact is a short
plain sentence, 8 to 20 words, capturing one atomic idea.

Rules:
- Include every specific number, date, name, and dollar figure that carries
  weight in the story.
- Include the ONE reason this news matters (as stated or clearly implied).
- Include the ONE-BEST direct quote if the source has one that is central.
- Do NOT invent facts. Every fact must be verifiable from the article text.
- Do NOT include throat-clearing or context that is common knowledge.

Return ONLY the JSON array. No prose, no code fences, no explanation.

Headline: {title}

Article:
{source}
"""


COVERAGE_PROMPT = """You are checking whether a news briefing preserves the
must-include facts from the original article.

For each fact below, answer YES if the briefing communicates the same idea
(even if worded differently), or NO if the fact is missing, contradicted, or
so weakened that a listener would not understand it.

Return a JSON object shaped like:
{{"covered": [true, false, ...], "missing_ids": [1, 3], "notes": "brief"}}

The `covered` array must have exactly {n} booleans in the same order as the
facts. `missing_ids` lists the 1-indexed positions where covered is false.
`notes` is ONE short sentence, empty string if everything covers.

MUST-INCLUDE facts:
{facts}

Briefing to check:
{briefing}
"""


@dataclass
class KeyPoints:
    facts: list[str]              # raw fact list from distillation
    raw_response: str             # the raw LLM output for debugging


@dataclass
class CoverageResult:
    covered: list[bool]           # one bool per fact
    coverage_pct: float           # 0.0 - 1.0
    missing: list[str]            # the actual missing facts
    notes: str


def _call(prompt: str, temperature: float = 0.2, max_tokens: int = 900) -> str:
    client = _get_client()
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config={"temperature": temperature, "max_output_tokens": max_tokens},
    )
    return (resp.text or "").strip()


def _extract_json(raw: str) -> str:
    """Strip code fences and stray prose."""
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    # If wrapped in more prose, grab the first {...} or [...] block
    m = re.search(r"([\[{].*[\]}])", s, re.S)
    return m.group(1) if m else s


def distill(title: str, source: str) -> KeyPoints | None:
    raw = _call(DISTILL_PROMPT.format(title=title, source=source[:12000]),
                temperature=0.2, max_tokens=800)
    if not raw:
        return None
    try:
        facts = json.loads(_extract_json(raw))
        if not isinstance(facts, list) or not (5 <= len(facts) <= 10):
            return None
        facts = [str(f).strip() for f in facts if isinstance(f, (str, int, float))]
        return KeyPoints(facts=facts, raw_response=raw)
    except json.JSONDecodeError:
        return None


def coverage(facts: list[str], briefing: str) -> CoverageResult | None:
    facts_bulleted = "\n".join(f"{i+1}. {f}" for i, f in enumerate(facts))
    raw = _call(
        COVERAGE_PROMPT.format(n=len(facts), facts=facts_bulleted, briefing=briefing),
        temperature=0.0, max_tokens=400,
    )
    if not raw:
        return None
    try:
        obj = json.loads(_extract_json(raw))
        cov = obj.get("covered", [])
        if len(cov) != len(facts):
            return None
        cov = [bool(x) for x in cov]
        missing = [facts[i] for i, ok in enumerate(cov) if not ok]
        return CoverageResult(
            covered=cov,
            coverage_pct=sum(cov) / len(cov) if cov else 0.0,
            missing=missing,
            notes=str(obj.get("notes", "")),
        )
    except json.JSONDecodeError:
        return None
