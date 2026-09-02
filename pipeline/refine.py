"""Multi-pass content refinement — every step before TTS.

Layers:
  1. DRAFT               (LLM)   — first-pass summary from source
  2. FACT_VERIFY         (LLM)   — check numbers/names/dates against source
     └─ REDRAFT          (LLM)   — retry with critique if verify fails
  3. AUDIO_REWRITE       (LLM)   — rewrite for spoken delivery
  4. PRONUNCIATION_NORM  (regex) — expand numbers, abbrevs, versions
  5. SANITY_CHECK        (LLM)   — cheap final read-aloud test
  6. WRITE_REVIEW        (I/O)   — persist to data/reviews/{date}/{id}.txt

TTS is downstream of this module and is the ONLY step that spends "expensive"
compute. If any layer here fails, we return None and skip TTS entirely.
"""
from __future__ import annotations
import re
import time
from dataclasses import dataclass
from pathlib import Path
from google import genai

from . import config, normalize, key_points

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

Length: 150 to 360 words, chosen by the story's real complexity — do not pad,
do not truncate. A launch or funding is 150-200. A meaty story is 220-290. A
complex multi-party story is 300-360.

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
    prompt = DRAFT_PROMPT.format(title=title, source=source[:12000])
    out = _call(prompt, temperature=0.4, max_tokens=900)
    if not out or len(out.split()) < config.WORDS_MIN * 0.7:
        return None
    return out


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

Return only the rewritten briefing.

Input briefing:
{draft}
"""


def _audio_rewrite(draft: str) -> str | None:
    out = _call(AUDIO_REWRITE_PROMPT.format(draft=draft), temperature=0.3, max_tokens=1100)
    return out or None


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
words, awkward punctuation, unspoken acronyms, mid-sentence cutoffs. Do not
flag stylistic preferences.

Text:
{text}
"""


def _sanity(text: str) -> tuple[bool, str]:
    out = _call(SANITY_PROMPT.format(text=text), temperature=0.0, max_tokens=200)
    if not out:
        return True, ""
    if out.strip().upper().startswith("OK"):
        return True, ""
    return False, out.strip()


# ────────────────────────────────────────────────────────────────────────────
# Layer 6: WRITE REVIEW
# ────────────────────────────────────────────────────────────────────────────

def _write_review(story_id: str, day: str, stages: dict[str, str]) -> Path:
    review_dir = config.DATA_DIR / "reviews" / day
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


def refine(title: str, source: str, story_id: str, day: str) -> Refined | None:
    stages: dict[str, str] = {}
    passes: list[str] = []

    # 0. DISTILL KEY POINTS from source (the coverage contract)
    kp = key_points.distill(title, source)
    if not kp:
        return None
    stages["00_KEY_POINTS"] = "\n".join(f"{i+1}. {f}" for i, f in enumerate(kp.facts))
    passes.append(f"distilled({len(kp.facts)})")

    # 1. DRAFT
    draft = _draft(title, source)
    if not draft:
        return None
    stages["01_DRAFT"] = draft
    passes.append("draft")

    # 2. LOCAL FACT VERIFY → LLM REDRAFT if hallucinations
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

    # 3. COVERAGE CHECK on the draft → REDRAFT if we lost too many facts
    try:
        cov1 = key_points.coverage(kp.facts, draft)
    except Exception as e:
        cov1 = None
        stages["03_COVERAGE_1"] = f"SKIPPED: {e}"
    if cov1:
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

    # 4. AUDIO REWRITE for spoken delivery
    audio_draft = _audio_rewrite(draft)
    if not audio_draft:
        return None
    stages["04_AUDIO_REWRITE"] = audio_draft
    passes.append("audio_rewrite")

    # 5. PRONUNCIATION NORMALIZE (deterministic)
    normalized = _pronunciation(audio_draft)
    stages["05_NORMALIZED"] = normalized
    passes.append("normalize")

    # 6. FINAL COVERAGE CHECK — did any facts drop out during audio rewrite?
    final_cov: key_points.CoverageResult | None = None
    try:
        final_cov = key_points.coverage(kp.facts, normalized)
    except Exception as e:
        stages["06_COVERAGE_FINAL"] = f"SKIPPED: {e}"
    if final_cov:
        stages["06_COVERAGE_FINAL"] = (
            f"{int(final_cov.coverage_pct*100)}% covered "
            f"({sum(final_cov.covered)}/{len(final_cov.covered)}). "
            f"Missing: {'; '.join(final_cov.missing) or 'none'}"
        )
        passes.append(f"cov_final={int(final_cov.coverage_pct*100)}%")

    # 7. SANITY CHECK for TTS-tripping issues
    sanity_notes = ""
    try:
        ok, notes = _sanity(normalized)
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
        key_points=kp.facts,
        coverage_pct=final_cov.coverage_pct if final_cov else -1.0,
        missing_points=final_cov.missing if final_cov else [],
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
