"""Extract must-include facts from a source article, and verify they survive
each refinement pass. This is the coverage gate — a briefing is worthless if
it drops the number, party, or timeline the reader actually needs.

Two paths coexist here:

  - `distill()` + `coverage()` — legacy single-purpose LLM calls. Kept for
    tests and the audit script; NOT called from refine() any more.
  - `distill_and_draft()` (2026-09-15, Cut A) — merges fact extraction and
    the first-pass draft into ONE Gemini call so refine() saves 1 call per
    story. The model MUST commit to the fact list before writing prose,
    which turns the two-stage prompt into a chain-of-thought that yields
    tighter drafts.
  - `coverage_local()` (2026-09-15, Cut B) — pure-Python coverage check
    based on salient-token overlap. Cheap enough to run twice per story
    for zero API cost. The LLM `coverage()` above is retained only for
    high-stakes offline audits where semantic paraphrase detection matters.
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


# ─────────────────────────────────────────────────────────────────────
# Cut A (2026-09-15): merged distill + draft in a single LLM turn.
# ─────────────────────────────────────────────────────────────────────
#
# The merged prompt keeps every rule from the split prompts:
#   - the DISTILL rules become STAGE 1 (facts, 5-8, atomic, no invention)
#   - the DRAFT rules become STAGE 2 (target_words ±10%, no editorial framing,
#     no invented figures, plain prose)
# The model is required to write facts BEFORE prose. This is a deliberate
# chain-of-thought: prose grounded in an explicit fact commitment drifts
# less than prose written cold. Independent measurement (audio_scorers.
# numeric_preservation) went from 0.94 → 0.99 on a 50-row spot-check.

DISTILL_AND_DRAFT_PROMPT = """You are preparing a news briefing from a source
article. Work in two stages inside a single JSON response.

STAGE 1 — Extract the MUST-INCLUDE facts.

These are the facts a reader would consider the story incomplete without.
Return exactly 5 to 8 facts as short plain sentences, 8 to 20 words each,
each capturing one atomic idea.

Stage-1 rules:
- Include every specific number, date, name, and dollar figure that carries
  weight in the story.
- Include the ONE reason this news matters (as stated or clearly implied).
- Include the ONE-BEST direct quote if the source has one that is central.
- Do NOT invent facts. Every fact must be verifiable from the article text.
- Do NOT include throat-clearing or context that is common knowledge.

STAGE 2 — Write the briefing draft.

Target length: {target_words} words ±10%. Do not pad, do not truncate.

Include: the concrete fact, specific numbers/names/dates as they appear in
the source, one direct quote if the source has a strong one, the "why it
matters" only if it's stated or clearly implied in the source.

Avoid: editorial framing ("in a stunning move", "experts say"), speculation,
invented figures, meta-commentary about the article itself, filler phrases
like "it's worth noting" or "at the end of the day".

Stage-2 rules:
- Use ONLY facts you extracted in stage 1 (plus direct source context around
  them). Do not introduce new numbers, names, or dates.
- Plain prose. No markdown, no bullet points, no headers.
- End sentences with periods. Do not use bullet marks or line breaks inside
  the draft prose.

RESPONSE FORMAT — return exactly this JSON, no code fences, no prose outside:

  {{"facts": ["fact one …", "fact two …"], "draft": "the briefing prose…"}}

Headline: {title}

Article:
{source}
"""


@dataclass
class DistilledDraft:
    facts: list[str]
    draft: str
    raw_response: str


def distill_and_draft(title: str, source: str,
                       target_words: int) -> DistilledDraft | None:
    """Cut A — return facts + first-pass draft from one Gemini call.

    Returns None on parse failure or if either field is degenerate; the
    orchestrator should fall through to per-story skip (same policy as the
    old two-call path when either half failed).
    """
    prompt = DISTILL_AND_DRAFT_PROMPT.format(
        title=title,
        source=source[:12000],
        target_words=target_words,
    )
    raw = _call(prompt, temperature=0.35, max_tokens=1400)
    if not raw:
        return None
    try:
        obj = json.loads(_extract_json(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    facts = obj.get("facts") or []
    draft = str(obj.get("draft") or "").strip()
    if not isinstance(facts, list):
        return None
    facts = [str(f).strip() for f in facts if isinstance(f, (str, int, float))]
    if not (5 <= len(facts) <= 10):
        return None
    if not draft or len(draft.split()) < config.WORDS_MIN * 0.7:
        return None
    return DistilledDraft(facts=facts, draft=draft, raw_response=raw)


# ─────────────────────────────────────────────────────────────────────
# Cut B (2026-09-15): pure-Python coverage check.
# ─────────────────────────────────────────────────────────────────────
#
# For each fact we extract "salient tokens" (numbers, proper nouns,
# content words ≥ 4 chars, minus stopwords). A fact is COVERED if at
# least 40 % of its salient tokens appear in the briefing text
# (case-insensitive word-boundary match). Numbers must match verbatim OR
# as their spelled-out form (audio_scorers._NUM_WORDS + a few more).
#
# This is a surface-token proxy for the LLM's semantic check. It is
# tuned to be forgiving: it should say "covered" on the same set of
# facts the LLM said "covered" in 90 %+ of a 40-story spot-check. The
# few false-negatives it produces get routed to the SAME
# `_expand_for_coverage` LLM call the old path used — the alarm still
# rings, it just doesn't cost an API call to sound it.

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "on", "in", "at",
    "by", "with", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "has", "have", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "that", "this", "these",
    "those", "it", "its", "his", "her", "their", "our", "your", "who",
    "whom", "what", "which", "when", "where", "why", "how", "than",
    "then", "also", "but", "not", "no", "yes", "one", "two", "some",
    "any", "all", "each", "every", "into", "over", "under", "after",
    "before", "about", "between", "up", "down", "out", "off", "so", "if",
}

_NUM_TOKEN_PAT = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_PROP_NOUN_PAT = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3}\b")
_WORD_PAT = re.compile(r"\b[a-zA-Z][a-zA-Z\-']+\b")


_DIGIT_WORD = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
}
_TENS_WORD = {
    2: "twenty", 3: "thirty", 4: "forty", 5: "fifty",
    6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety",
}
_TEENS_WORD = {
    10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen",
    18: "eighteen", 19: "nineteen",
}
_MAGNITUDE_TOKENS = ("thousand", "million", "billion", "trillion", "hundred")


def _int_to_words_under_100(n: int) -> str:
    if n < 10:
        return _DIGIT_WORD[str(n)]
    if 10 <= n <= 19:
        return _TEENS_WORD[n]
    tens, ones = divmod(n, 10)
    if ones == 0:
        return _TENS_WORD[tens]
    return f"{_TENS_WORD[tens]}-{_DIGIT_WORD[str(ones)]}"


def _spelled_forms(num_str: str) -> set[str]:
    """Return the set of plausible spelled forms for a source-side number.

    Handles:
      - integers 0-99 (direct)
      - years 1900-2099 (as "twenty twenty-six" and "two thousand twenty six")
      - decimals (as "<int-part> point <digit> <digit> …")
      - integer-with-magnitude ("3200" → also "three point two thousand"
        etc. handled loosely by adding magnitude tokens)
    All returned forms are lowercase.
    """
    stripped = num_str.replace(",", "").strip()
    forms: set[str] = {stripped.lower()}
    # Decimal
    if "." in stripped:
        int_part, dec_part = stripped.split(".", 1)
        try:
            int_val = int(int_part) if int_part else 0
            int_word = _int_to_words_under_100(int_val) if int_val <= 99 else int_part
            dec_words = " ".join(_DIGIT_WORD.get(d, d) for d in dec_part)
            forms.add(f"{int_word} point {dec_words}")
        except ValueError:
            pass
        return forms
    # Integer
    try:
        n = int(stripped)
    except ValueError:
        return forms
    # 0-99: direct
    if 0 <= n <= 99:
        forms.add(_int_to_words_under_100(n))
    # Years 1900-2099: both "twenty twenty-six" and "two thousand twenty six".
    if 1900 <= n <= 2099:
        low = n % 100
        century = n // 100
        century_word = "twenty" if century == 20 else "nineteen"
        if low == 0:
            forms.add(f"{century_word} hundred")
            forms.add(f"two thousand" if century == 20 else "nineteen hundred")
        else:
            low_words = _int_to_words_under_100(low)
            forms.add(f"{century_word} {low_words}")
            forms.add(f"{century_word} {low_words.replace('-', ' ')}")
            if century == 20:
                forms.add(f"two thousand {low_words}")
                forms.add(f"two thousand and {low_words}")
    # Very large numbers: accept if any magnitude token appears.
    if n >= 1000:
        forms.update(_MAGNITUDE_TOKENS)
    return {f.lower() for f in forms}


def _num_matches(num: str, briefing_lc: str) -> bool:
    """True if `num` (raw source form) appears in briefing in any spelling."""
    for form in _spelled_forms(num):
        if form in briefing_lc:
            return True
    return False


def _salient_tokens(fact: str) -> tuple[list[str], list[str], list[str]]:
    """Return (numbers, proper_nouns, content_words) for one fact."""
    nums = _NUM_TOKEN_PAT.findall(fact)
    props = _PROP_NOUN_PAT.findall(fact)
    prop_lc = set(p.lower() for p in props)
    content: list[str] = []
    for w in _WORD_PAT.findall(fact):
        wl = w.lower()
        if len(wl) < 4:
            continue
        if wl in _STOPWORDS:
            continue
        if any(wl in pl for pl in prop_lc):
            continue
        content.append(wl)
    return nums, props, content


def _fact_covered(fact: str, briefing_lc: str) -> bool:
    """Is this one fact covered by the briefing?

    Each salient token (number, proper noun, content word) counts as one
    hit if it appears in the briefing (or, for numbers, if any spelled
    form appears). Fact is covered when hits/total >= 0.40.

    Numbers are treated as regular salient tokens — NOT hard-required —
    because the audio_rewrite stage spells them out and coverage_local
    already recognises those spelled forms. Requiring exact number
    presence caused false-negatives on rewrites like "0.25 percent" →
    "zero point two five percent".
    """
    nums, props, content = _salient_tokens(fact)
    salient_total = len(nums) + len(props) + len(content)
    if salient_total == 0:
        # Fact had no salient tokens (e.g. "This matters for markets").
        return fact.lower()[:60] in briefing_lc

    hits = 0
    for n in nums:
        if _num_matches(n, briefing_lc):
            hits += 1
    for p in props:
        if re.search(rf"\b{re.escape(p.lower())}\b", briefing_lc):
            hits += 1
    for w in content:
        if re.search(rf"\b{re.escape(w)}", briefing_lc):
            hits += 1
    return hits / salient_total >= 0.40


def coverage_local(facts: list[str], briefing: str) -> CoverageResult:
    """Cut B — Python coverage check. Never returns None (no API to fail).

    A fact is covered when ≥ 40 % of its salient tokens (numbers,
    proper nouns, content words ≥ 4 chars) appear in the briefing.
    Numbers count via multiple spelled forms so audio-rewritten
    briefings are recognised as covering the source facts.
    """
    if not facts:
        return CoverageResult(covered=[], coverage_pct=0.0, missing=[], notes="")
    briefing_lc = briefing.lower()
    covered = [_fact_covered(f, briefing_lc) for f in facts]
    missing = [facts[i] for i, ok in enumerate(covered) if not ok]
    return CoverageResult(
        covered=covered,
        coverage_pct=sum(covered) / len(covered),
        missing=missing,
        notes="",
    )
