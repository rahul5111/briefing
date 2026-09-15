"""Multi-pass content refinement — every step before TTS.

Layers (post-optimization 2026-09-15 — see Cut A/B/C/D below):
  1. DISTILL_AND_DRAFT   (LLM)   — extract facts AND write draft in one call
  2. FACT_VERIFY         (LLM*)  — regex; LLM redraft only if bad facts found
  3. COVERAGE            (Python)— salient-token overlap on facts vs draft
     └─ EXPAND           (LLM*)  — only when coverage < 0.85
  4. AUDIO_REWRITE       (LLM)   — one call returning {stakes, audio_body}
  5. PRONUNCIATION_NORM  (regex) — expand numbers, abbrevs, versions
  6. AUDIO_SCORERS       (regex) — rule-based TTS sanity (audio_scorers.py)
  7. WRITE_REVIEW        (I/O)   — persist to data/reviews/{date}/{id}.txt

Gemini call count per always-fire story: 2 (was 7).
  A. distill_and_draft (was distill + _draft)                = 1 (was 2)
  B. coverage checks × 2 → Python                             = 0 (was 2)
  C. audio_rewrite_with_stakes (was _why_matters + _audio…)   = 1 (was 2)
  D. sanity → audio_scorers                                   = 0 (was 1)
Conditional (bad facts / low coverage) still uses LLM: +0-2.

TTS is downstream of this module and is the ONLY step that spends "expensive"
compute. If any layer here fails, we return None and skip TTS entirely.
"""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from google import genai

from . import config, normalize, key_points
from .eval import audio_scorers

COVERAGE_THRESHOLD = 0.85   # % of must-include facts that must be present


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _call(prompt: str, temperature: float = 0.4, max_tokens: int = 900) -> str:
    client = _get_client()
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config={"temperature": temperature, "max_output_tokens": max_tokens},
            )
            return (resp.text or "").strip()
        except Exception as e:
            msg = str(e)
            if "404" in msg or "PERMISSION" in msg:
                raise
            if "429" in msg:
                m = re.search(r"retry in (\d+(?:\.\d+)?)s", msg)
                wait = float(m.group(1)) if m else min(60, 8 * (attempt + 1))
                if attempt == 2 or wait > 90:
                    raise
                time.sleep(min(wait + 1, 90))
                continue
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return ""


# ────────────────────────────────────────────────────────────────────────────
# Layer 1: DRAFT
# ────────────────────────────────────────────────────────────────────────────

DRAFT_PROMPT = """You are drafting a news briefing for a private listener.

Target length: {target_words} words ±10%. Do not pad, do not truncate.

Include: the concrete fact, specific numbers/names/dates as they appear in the
source, one direct quote if the source has a strong one, the "why it matters"
only if it's stated or clearly implied in the source.

Avoid: editorial framing ("in a stunning move", "experts say"), speculation,
invented figures, meta-commentary about the article itself, filler phrases
like "it's worth noting" or "at the end of the day".

Format: plain prose. No markdown, no bullet points, no headers. Return only
the briefing text.

Headline: {title}

Article:
{source}
"""


def _draft(title: str, source: str) -> str | None:
    # B-47: pass length as a deterministic parameter (source_words × 0.35
    # clamped to [WORDS_MIN, WORDS_MAX]) rather than asking the model to
    # self-select from a wide band. Removes bimodal band-edge failure
    # mode where flash-lite writes either 150 or 360 with nothing in
    # between.
    source_words = len(source.split())
    target = int(round(source_words * 0.35))
    target = max(config.WORDS_MIN, min(config.WORDS_MAX, target))
    prompt = DRAFT_PROMPT.format(
        title=title,
        source=source[:12000],
        target_words=target,
    )
    out = _call(prompt, temperature=0.4, max_tokens=900)
    if not out or len(out.split()) < config.WORDS_MIN * 0.7:
        return None
    return out


# ────────────────────────────────────────────────────────────────────────────
# Layer 2b: WHY-IT-MATTERS (new; explicitly asks the model to infer stakes)
# ────────────────────────────────────────────────────────────────────────────
#
# Persona audit finding P1-2: the draft prompt tells the model *not* to
# invent stakes if the source is silent. That's correct for facts, but it
# leaves 90% of announcements/listicles/PR-shaped stories with no "so what."
# This dedicated layer, run after DRAFT and before AUDIO_REWRITE, has
# permission to infer stakes conservatively. If nothing meaningful can be
# inferred, it returns NONE and the story is demoted.
WHY_MATTERS_PROMPT = """You are writing the ONE-SENTENCE "why it matters" line
for this briefing.

Say what it means for a professional reader of business, tech, and policy news:
- market impact (specific company or sector)
- precedent (regulatory, legal, editorial)
- affected population (numbers or geography)
- consequence downstream (what other actors will do)

Rules:
- ONE sentence, 12-28 words.
- Ground the inference in facts already in the briefing. Do not add new
  entities or numbers.
- If the briefing is a listicle, a shopping guide, a personality piece, or
  a bundle of unrelated items, return the single word: NONE
- Do not use throat-clearing phrases like "this matters because" or "the
  significance is that". Just say it.
- Do not editorialise ("shockingly", "unprecedented"). Just state
  the consequence.

Return ONE sentence, or the literal word NONE.

Briefing:
{draft}
"""


def _why_matters(draft: str) -> str | None:
    """Return a one-sentence stakes line, or None if the story is fluff."""
    out = _call(WHY_MATTERS_PROMPT.format(draft=draft), temperature=0.2, max_tokens=90)
    if not out:
        return None
    out = out.strip().rstrip(".")
    if out.upper() == "NONE" or len(out.split()) < 8:
        return None
    return out + "."


# ────────────────────────────────────────────────────────────────────────────
# Layer 2: FACT VERIFY (regex + LLM)
# ────────────────────────────────────────────────────────────────────────────

_NUM = re.compile(r"\b\d[\d,\.]*\b")
_PROP = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3}\b")
_COMMON = {
    "The", "A", "An", "This", "That", "It", "He", "She", "They", "We",
    "But", "And", "Or", "So", "For", "If", "Then", "According", "While",
    "Meanwhile", "However", "Also", "As", "In", "On", "At", "By", "From",
    "To", "With", "Of",
}


def _local_verify(draft: str, source: str) -> list[str]:
    """Return a list of sentences that contain facts not in the source."""
    src_lower = source.lower()
    bad: list[str] = []
    for s in re.split(r"(?<=[.!?])\s+", draft):
        # numbers
        for m in _NUM.findall(s):
            if m not in source and m.replace(",", "") not in source.replace(",", ""):
                bad.append(s.strip())
                break
        else:
            # proper nouns
            for m in _PROP.findall(s):
                first = m.split()[0]
                if first in _COMMON:
                    continue
                if m.lower() not in src_lower:
                    bad.append(s.strip())
                    break
    return bad


REDRAFT_PROMPT = """Your previous draft contains sentences with facts that are
NOT in the source:

{bad}

Rewrite the entire briefing. Drop or reword those sentences using only facts
from the source. Keep the same length, tone, and structure. Return only the
briefing text.

Source:
{source}

Previous draft:
{draft}
"""


def _redraft(draft: str, source: str, bad: list[str]) -> str | None:
    prompt = REDRAFT_PROMPT.format(
        bad="\n- " + "\n- ".join(bad[:8]),
        source=source[:12000],
        draft=draft,
    )
    out = _call(prompt, temperature=0.3, max_tokens=900)
    return out or None


# ────────────────────────────────────────────────────────────────────────────
# Layer 3: AUDIO REWRITE
# ────────────────────────────────────────────────────────────────────────────

AUDIO_REWRITE_PROMPT = """Rewrite this news briefing for SPOKEN audio delivery.
A neural voice will read it aloud. It must sound natural to the ear.

Worked example — this is what "spoken form" looks like:

  INPUT:  Reuters reports the Fed cut rates by 0.25%, and the API price
          for GPT-4 fell $40M in Q3 2026.
  OUTPUT: The Federal Reserve cut interest rates by zero point two five
          percent, Reuters reports. The A. P. I. price for G. P. T. four
          fell forty million dollars in the third quarter of twenty
          twenty-six.

Hard rules — apply every single one:

1. SPELL OUT ALL NUMBERS. "3.8" becomes "three point eight". "40,000" becomes
   "forty thousand". "2026" becomes "twenty twenty-six". "$40M" becomes "forty
   million dollars". Version numbers, years, currency, percentages, everything.

2. SPELL OUT ACRONYMS on first use. "AI" → "A. I.". "GDP" → "G. D. P.".
   "HTTPS" → "H. T. T. P. S.". Use periods between the letters — the voice
   pauses on them correctly.

3. SHORT SENTENCES. Aim for 12-20 words per sentence. Break long ones with
   periods, not commas. A period is a pause; a comma is not.

4. NO dashes, no parentheses, no semicolons, no lists, no colons. These do
   not work in speech. Rephrase around them.

5. NO throat-clearing openings like "In a recent development" or "It was
   announced today". Start with the fact.

6. If a name is unusual (foreign, technical, or made-up), add a comma-pause
   before it so the voice slows down.

7. Keep every fact from the input. Do not add new facts. Do not remove facts
   unless they contain a symbol or number you cannot spell out cleanly.

8. IN-LINE ATTRIBUTION. Name the outlet exactly once, in the second or third
   sentence, in-line: "Reuters reports…", "the B. B. C. characterises it as…",
   "according to The Hindu…". Use the outlet name given as {source_name}. Do
   not append attribution at the end; weave it mid-flow.

9. STAKES LINE. If a "why it matters" line is supplied below, weave it as
   the final sentence of the second paragraph — do not tack it on as a
   separate paragraph at the end. Rephrase it to match your prose voice.

Outlet: {source_name}
Why-it-matters line (may be empty): {stakes}

Input briefing:
{draft}
"""


def _audio_rewrite(draft: str, source_name: str = "", stakes: str = "") -> str | None:
    out = _call(
        AUDIO_REWRITE_PROMPT.format(
            draft=draft,
            source_name=source_name or "the source",
            stakes=stakes or "(no stakes line supplied — do not fabricate)",
        ),
        temperature=0.3, max_tokens=1200,
    )
    return out or None


# ─────────────────────────────────────────────────────────────────────
# Cut C (2026-09-15): merged why-it-matters + audio-rewrite in one call.
# ─────────────────────────────────────────────────────────────────────
#
# The merged prompt inlines ALL of:
#   - the 9 hard audio rules from AUDIO_REWRITE_PROMPT (unchanged verbatim)
#   - the worked example from AUDIO_REWRITE_PROMPT (unchanged verbatim)
#   - the stakes-line rules from WHY_MATTERS_PROMPT (unchanged verbatim)
#   - a stakes weaving rule (was rule 9 of AUDIO_REWRITE, retained here)
#
# Structure — the model MUST derive stakes FIRST, before writing the
# audio body. This is a deliberate chain-of-thought:
#   1) the model commits to a one-sentence "why it matters" grounded in
#      the input, or emits the sentinel "NONE" if the story is fluff
#   2) it then rewrites for audio, weaving that stakes sentence into
#      paragraph 2 as before
# NONE stakes → the caller flags the story `thin=True`, matching the old
# path exactly.

AUDIO_REWRITE_WITH_STAKES_PROMPT = """You are rewriting a news briefing for
SPOKEN audio delivery AND deriving its one-sentence "why it matters" line.
A neural voice will read your output aloud. It must sound natural to the ear.

You produce ONE JSON object with two fields:
  {{"stakes": "<one sentence, 12-28 words, OR the literal word NONE>",
    "audio_body": "<the spoken-form briefing prose>"}}

────────────────────────────────────────────────────────────────────
STAKES rules (fill this first, before writing audio_body):
────────────────────────────────────────────────────────────────────

Say what this news means for a professional reader of business, tech, and
policy news:
  - market impact (specific company or sector)
  - precedent (regulatory, legal, editorial)
  - affected population (numbers or geography)
  - consequence downstream (what other actors will do)

Stakes rules:
- ONE sentence, 12-28 words.
- Ground the inference in facts already in the input briefing. Do not add
  new entities or numbers.
- If the input is a listicle, a shopping guide, a personality piece, or a
  bundle of unrelated items, return exactly: NONE
- Do not use throat-clearing phrases like "this matters because" or "the
  significance is that". Just say it.
- Do not editorialise ("shockingly", "unprecedented"). Just state the
  consequence.

────────────────────────────────────────────────────────────────────
AUDIO_BODY rules (rewrite the input briefing for spoken delivery):
────────────────────────────────────────────────────────────────────

Worked example — this is what "spoken form" looks like:

  INPUT:  Reuters reports the Fed cut rates by 0.25%, and the API price
          for GPT-4 fell $40M in Q3 2026.
  OUTPUT: The Federal Reserve cut interest rates by zero point two five
          percent, Reuters reports. The A. P. I. price for G. P. T. four
          fell forty million dollars in the third quarter of twenty
          twenty-six.

Hard rules — apply every single one:

1. SPELL OUT ALL NUMBERS. "3.8" becomes "three point eight". "40,000" becomes
   "forty thousand". "2026" becomes "twenty twenty-six". "$40M" becomes "forty
   million dollars". Version numbers, years, currency, percentages, everything.

2. SPELL OUT ACRONYMS on first use. "AI" → "A. I.". "GDP" → "G. D. P.".
   "HTTPS" → "H. T. T. P. S.". Use periods between the letters — the voice
   pauses on them correctly.

3. SHORT SENTENCES. Aim for 12-20 words per sentence. Break long ones with
   periods, not commas. A period is a pause; a comma is not.

4. NO dashes, no parentheses, no semicolons, no lists, no colons. These do
   not work in speech. Rephrase around them.

5. NO throat-clearing openings like "In a recent development" or "It was
   announced today". Start with the fact.

6. If a name is unusual (foreign, technical, or made-up), add a comma-pause
   before it so the voice slows down.

7. Keep every fact from the input. Do not add new facts. Do not remove facts
   unless they contain a symbol or number you cannot spell out cleanly.

8. IN-LINE ATTRIBUTION. Name the outlet exactly once, in the second or third
   sentence, in-line: "Reuters reports…", "the B. B. C. characterises it as…",
   "according to The Hindu…". Use the outlet name given as {source_name}. Do
   not append attribution at the end; weave it mid-flow.

9. STAKES WEAVING. If your `stakes` field is NOT the literal word NONE,
   rephrase that sentence to match your prose voice and weave it as the
   final sentence of the second paragraph of audio_body. Do NOT tack it on
   as a separate paragraph at the end. If your `stakes` is NONE, do not
   invent stakes in the audio_body either — write a straight-facts version.

────────────────────────────────────────────────────────────────────
Output format:

Return ONLY the JSON object. No prose outside, no code fences, no comments.
Example valid response (illustrative — do not copy the words):

  {{"stakes":"The rate cut lowers borrowing costs for U. S. small businesses through the fourth quarter.","audio_body":"The Federal Reserve cut interest rates by zero point two five percent, Reuters reports. ..."}}

────────────────────────────────────────────────────────────────────

Outlet: {source_name}

Input briefing:
{draft}
"""


@dataclass
class AudioWithStakes:
    stakes: str          # empty string if the model emitted NONE
    audio_body: str      # spoken-form prose


def _audio_rewrite_with_stakes(draft: str, source_name: str = "") -> AudioWithStakes | None:
    """Cut C — one Gemini call returning both stakes and audio_body.

    Returns None on parse failure (caller falls through to skip, same
    policy as the old path when either the why_matters or audio_rewrite
    call returned empty). An emitted `NONE` stakes yields `stakes=""` and
    the caller sets `thin=True` on the Refined record.
    """
    prompt = AUDIO_REWRITE_WITH_STAKES_PROMPT.format(
        draft=draft,
        source_name=source_name or "the source",
    )
    raw = _call(prompt, temperature=0.3, max_tokens=1600)
    if not raw:
        return None
    # Strip fences the model may have wrapped around the JSON.
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        s = m.group(0)
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    stakes_raw = str(obj.get("stakes", "")).strip()
    body = str(obj.get("audio_body", "")).strip()
    if not body:
        return None
    # Match the legacy _why_matters filter: strip trailing period, treat
    # "NONE" (case-insensitive) or fewer than 8 words as no-stakes.
    stakes_norm = stakes_raw.rstrip(".").strip()
    if stakes_norm.upper() == "NONE" or len(stakes_norm.split()) < 8:
        stakes_out = ""
    else:
        stakes_out = stakes_norm + "."
    return AudioWithStakes(stakes=stakes_out, audio_body=body)


# ────────────────────────────────────────────────────────────────────────────
# Layer 4: PRONUNCIATION NORMALIZE (safety net; deterministic)
# ────────────────────────────────────────────────────────────────────────────

def _pronunciation(text: str) -> str:
    return normalize.normalize(text)


# ────────────────────────────────────────────────────────────────────────────
# Layer 5: SANITY CHECK
# ────────────────────────────────────────────────────────────────────────────

SANITY_PROMPT = """Read this text as if you were the voice reading it aloud to
a listener. Report ONE of exactly two things:

  OK
  ISSUES: <comma-separated brief descriptions>

Only flag issues that will genuinely trip a neural TTS voice or sound wrong to
a human ear: digits or symbols that were not spelled out, sentences over 30
words, awkward punctuation, unspoken/unspaced acronyms, mid-sentence cutoffs.

DO NOT flag any of the following — they are the deliberate TTS-ready format:
- Letter-spaced acronyms in "N. B. A." or "N B A" or "N B A." form
- Numbers spelled out in words ("thirty million dollars")
- Years spelled as "twenty twenty-six" or "nineteen ninety-seven"

Do not flag stylistic preferences.

Text:
{text}
"""


def _sanity(text: str) -> tuple[bool, str]:
    """LEGACY LLM sanity check. Not called from refine() any more —
    superseded by `_sanity_local()` (Cut D). Kept only so external
    callers / tests can still invoke it."""
    out = _call(SANITY_PROMPT.format(text=text), temperature=0.0, max_tokens=200)
    if not out:
        return True, ""
    if out.strip().upper().startswith("OK"):
        return True, ""
    return False, out.strip()


# ─────────────────────────────────────────────────────────────────────
# Cut D (2026-09-15): Python sanity check via audio_scorers.
# ─────────────────────────────────────────────────────────────────────
#
# The old SANITY_PROMPT flagged: bare digits/symbols, sentences > 30 words,
# awkward punctuation, unspaced acronyms, mid-sentence cutoffs. All of
# that is already implemented deterministically in audio_scorers.py
# (B-45) as: numeric_preservation, sentence_length_dist,
# forbidden_punctuation, acronym_letter_spacing. Wiring the scorers in
# here replaces one LLM call per story with zero API cost, and gives
# structured details for the review file instead of prose.

def _sanity_local(text: str, source: str, source_name: str) -> tuple[bool, str]:
    """Cut D — audio_scorers wrapper. Returns (all_passed, notes)."""
    results = audio_scorers.run_all(source=source, rewrite=text,
                                     source_name=source_name)
    all_ok = audio_scorers.all_passed(results)
    if all_ok:
        return True, ""
    fails = [f"{r.name}: score={r.score:.2f} {r.details}"
             for r in results if not r.passed]
    return False, "; ".join(fails)


# ────────────────────────────────────────────────────────────────────────────
# Layer 6: WRITE REVIEW
# ────────────────────────────────────────────────────────────────────────────

def _write_review(story_id: str, day: str, stages: dict[str, str]) -> Path:
    review_dir = config.REVIEWS_DIR / day
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / f"{story_id}.txt"
    with path.open("w") as f:
        for name, text in stages.items():
            f.write(f"═══ {name} ═══\n\n{text}\n\n")
    return path


# ────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class Refined:
    text: str                 # what TTS will consume
    word_count: int
    passes_used: list[str]    # for logging
    sanity_notes: str         # any flags that survived
    key_points: list[str]     # distilled must-include facts
    coverage_pct: float       # 0.0-1.0 — how many key points made it into the final text
    missing_points: list[str] # facts that dropped out
    stakes: str = ""          # the "why it matters" line (empty if content-thin)
    thin: bool = False        # True when the story failed the stakes check


_DIGEST_TITLE_PATTERNS = re.compile(
    r"^(the download|up first|the daily brief|briefing:|morning brief|"
    r"quick catch[- ]?up|news roundup|weekly digest|top stories|"
    r"today'?s? headlines|around the web|links for|five things|"
    r"today'?s? papers|weekend reads)",
    re.IGNORECASE,
)


def _looks_like_digest(title: str, source: str) -> bool:
    """Bundle-post detection. Two signals:
       1) Title matches a known digest template.
       2) Body has 4+ ALL-CAPS or bold-style section markers with unrelated
          named entities in each.
    Either triggers the skip path — these are guaranteed to produce
    incoherent 6-in-1 summaries.
    """
    if _DIGEST_TITLE_PATTERNS.search(title.strip()):
        return True
    # Structural: count leading-uppercase-word or numeric-list prefixes
    # (a lot of digest posts have "1.", "2.", "---", or bold labels).
    strong_markers = len(re.findall(r"(?:^|\n)\s*(?:\d+[.)]|—|—|\*\*[A-Z])", source))
    if strong_markers >= 6:
        # Confirm by checking that at least 4 sections start with different
        # capitalised nouns (rough proxy for unrelated stories).
        heads = re.findall(r"(?:^|\n)\s*(?:\d+[.)]|\*\*)\s*([A-Z][a-zA-Z]+)", source)
        if len(set(heads[:6])) >= 4:
            return True
    return False


def refine(title: str, source: str, story_id: str, day: str, source_name: str = "") -> Refined | None:
    stages: dict[str, str] = {}
    passes: list[str] = []

    # 0a. BUNDLE-POST GUARD (persona audit P1-3): digests like MIT TR
    #     "The Download" and NPR "Up First" bundle 5-6 unrelated stories
    #     into one post. The pipeline turns them into incoherent
    #     "Miami crash + Germany election + menopause + Rwanda" summaries
    #     Priya can't follow. Skip them entirely.
    if _looks_like_digest(title, source):
        print(f"  digest post detected, skipping: {title[:80]}")
        return None

    # 0. DISTILL_AND_DRAFT — one Gemini call returns both the fact list
    #    (coverage contract) and the first-pass draft (Cut A).
    source_words = len(source.split())
    target = max(config.WORDS_MIN,
                 min(config.WORDS_MAX, int(round(source_words * 0.35))))
    dd = key_points.distill_and_draft(title, source, target_words=target)
    if not dd:
        return None
    facts = dd.facts
    draft = dd.draft
    stages["00_KEY_POINTS"] = "\n".join(f"{i+1}. {f}" for i, f in enumerate(facts))
    stages["01_DRAFT"] = draft
    passes.append(f"distilled({len(facts)})")
    passes.append("draft")

    # 2. LOCAL FACT VERIFY → LLM REDRAFT if hallucinations
    #    (unchanged — conditional LLM call, already cheap on average).
    bad = _local_verify(draft, source)
    if bad:
        redrafted = _redraft(draft, source, bad)
        if redrafted:
            draft = redrafted
            stages["02_REDRAFT_HALLUCINATIONS"] = draft
            passes.append("redraft_hallucinations")
            bad2 = _local_verify(draft, source)
            if bad2:
                kept = [s for s in re.split(r"(?<=[.!?])\s+", draft) if s.strip() not in bad2]
                draft = " ".join(kept)
                stages["02b_TRIMMED"] = draft
                passes.append("trim")

    # 3. COVERAGE CHECK on the draft (Python — Cut B). No API call.
    #    Falls through to `_expand_for_coverage` ONLY when the Python
    #    check says < threshold, matching the old policy but skipping
    #    the LLM verify step upstream.
    cov1 = key_points.coverage_local(facts, draft)
    stages["03_COVERAGE_1"] = (
        f"{int(cov1.coverage_pct*100)}% covered "
        f"({sum(cov1.covered)}/{len(cov1.covered)}). "
        f"Missing: {'; '.join(cov1.missing) or 'none'}"
    )
    passes.append(f"cov1={int(cov1.coverage_pct*100)}%")
    if cov1.coverage_pct < COVERAGE_THRESHOLD and cov1.missing:
        expand = _expand_for_coverage(draft, source, cov1.missing)
        if expand:
            draft = expand
            stages["03b_EXPANDED_FOR_COVERAGE"] = draft
            passes.append("expanded")

    if len(draft.split()) < config.WORDS_MIN * 0.7:
        return None

    # 4. AUDIO_REWRITE_WITH_STAKES (Cut C) — one Gemini call returns
    #    both stakes and audio_body. NONE stakes → thin story flag,
    #    matching legacy _why_matters behaviour.
    aws = _audio_rewrite_with_stakes(draft, source_name=source_name)
    if not aws:
        return None
    stakes = aws.stakes
    audio_draft = aws.audio_body
    stages["03c_WHY_MATTERS"] = stakes or "NONE — content-thin, no stakes inferable"
    stages["04_AUDIO_REWRITE"] = audio_draft
    passes.append(f"stakes={'y' if stakes else 'n'}")
    passes.append("audio_rewrite")

    # 5. PRONUNCIATION NORMALIZE (deterministic)
    normalized = _pronunciation(audio_draft)
    stages["05_NORMALIZED"] = normalized
    passes.append("normalize")

    # 6. FINAL COVERAGE CHECK — did any facts drop out during audio
    #    rewrite? Python again (Cut B). Informational; does not gate.
    final_cov = key_points.coverage_local(facts, normalized)
    stages["06_COVERAGE_FINAL"] = (
        f"{int(final_cov.coverage_pct*100)}% covered "
        f"({sum(final_cov.covered)}/{len(final_cov.covered)}). "
        f"Missing: {'; '.join(final_cov.missing) or 'none'}"
    )
    passes.append(f"cov_final={int(final_cov.coverage_pct*100)}%")

    # 7. SANITY CHECK for TTS-tripping issues — audio_scorers (Cut D).
    sanity_notes = ""
    try:
        ok, notes = _sanity_local(normalized, source=source,
                                   source_name=source_name)
        if not ok:
            sanity_notes = notes
        stages["07_SANITY"] = "OK" if ok else notes
        passes.append("sanity")
    except Exception as e:
        stages["07_SANITY"] = f"SKIPPED: {e}"

    # 8. WRITE REVIEW
    review_path = _write_review(story_id, day, stages)
    passes.append(f"reviewed→{review_path.name}")

    words = len(normalized.split())
    if words > config.WORDS_MAX * 1.2:
        chunks = re.split(r"(?<=[.!?])\s+", normalized)
        acc: list[str] = []
        for c in chunks:
            if sum(len(x.split()) for x in acc) + len(c.split()) > config.WORDS_MAX:
                break
            acc.append(c)
        normalized = " ".join(acc)
        words = len(normalized.split())

    return Refined(
        text=normalized,
        word_count=words,
        passes_used=passes,
        sanity_notes=sanity_notes,
        key_points=facts,
        coverage_pct=final_cov.coverage_pct,
        missing_points=final_cov.missing,
        stakes=stakes,
        thin=not bool(stakes),
    )


EXPAND_PROMPT = """Your current briefing is missing these must-include facts
from the source:

{missing}

Rewrite the briefing to include EVERY missing fact naturally. Preserve
everything that is already there. Keep the same tone and cadence. Do not add
speculation. Return only the rewritten briefing.

Source:
{source}

Current briefing:
{draft}
"""


def _expand_for_coverage(draft: str, source: str, missing: list[str]) -> str | None:
    out = _call(
        EXPAND_PROMPT.format(
            missing="\n- " + "\n- ".join(missing),
            source=source[:12000],
            draft=draft,
        ),
        temperature=0.25,
        max_tokens=1000,
    )
    return out or None
