"""B-45 rule-based audio-rewrite quality scorers.

Deterministic checks the audio_rewrite output must pass before it's
worth shipping any model upgrade or prompt change. These are gates,
not preferences — they answer "did the rewriter preserve the facts?"

Introduced as prerequisite scorers for the Phase-H model bake-off
(B-73). Also useful as characterisation tests on prompt changes
(B-28).

All scorers are pure functions of (source_text, rewrite_text). No LLM
calls. Meant to be cheap enough to run on every refined story if we
want, and mandatory to run before any model-change ships.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ScorerResult:
    name: str
    passed: bool
    score: float           # 0.0 – 1.0 where 1.0 is perfect
    details: dict


# ── Numeric preservation ─────────────────────────────────────────────

_NUM_PAT = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")

# Common cardinal spellings for 0–20 and multiples of ten.
_NUM_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four",
    5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
    10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen",
    18: "eighteen", 19: "nineteen",
    20: "twenty", 30: "thirty", 40: "forty", 50: "fifty",
    60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety",
    100: "hundred", 1000: "thousand", 1_000_000: "million",
    1_000_000_000: "billion", 1_000_000_000_000: "trillion",
}

_MAGNITUDE_TOKENS = ("thousand", "million", "billion", "trillion", "hundred")


def _spelled_form(n: int) -> Optional[str]:
    """Return a spelled form of `n` if it's a common cardinal."""
    if n in _NUM_WORDS:
        return _NUM_WORDS[n]
    return None


def numeric_preservation(source: str, rewrite: str) -> ScorerResult:
    """
    Every distinct number in source must appear in rewrite either
    verbatim OR as a spelled form OR as a magnitude token (e.g. '2.3B'
    accepts 'two point three billion').

    Ship gate: score ≥ 0.98.
    """
    source_nums = set(m.group().replace(",", "") for m in _NUM_PAT.finditer(source))
    if not source_nums:
        return ScorerResult("numeric_preservation", True, 1.0,
                            {"total": 0, "missing": []})
    rewrite_lc = rewrite.lower()
    missing = []
    for n in source_nums:
        found = False
        # verbatim (with or without comma-grouping)
        if n in rewrite_lc or f"{int(float(n)):,}" in rewrite_lc:
            found = True
        else:
            # spelled — try integer form
            try:
                as_int = int(float(n))
                spelled = _spelled_form(as_int)
                if spelled and spelled in rewrite_lc:
                    found = True
                # partial: any magnitude token when the number is large
                elif as_int >= 1000:
                    if any(t in rewrite_lc for t in _MAGNITUDE_TOKENS):
                        found = True
            except ValueError:
                pass
        if not found:
            missing.append(n)
    total = len(source_nums)
    score = 1.0 - (len(missing) / total)
    return ScorerResult(
        "numeric_preservation",
        passed=score >= 0.98,
        score=round(score, 3),
        details={"total": total, "missing": missing[:10]},
    )


# ── Acronym letter-spacing ──────────────────────────────────────────

# 2–5 caps, possibly with digits (e.g. GPT4, IPv6). Filter out
# ALL-CAPS words that aren't acronyms (e.g. section headers) by
# requiring the token to be flanked by non-cap context in source.
_ACRONYM_PAT = re.compile(r"\b([A-Z][A-Z0-9]{1,4})\b")


def acronym_letter_spacing(source: str, rewrite: str) -> ScorerResult:
    """
    Every acronym in source (2–5 caps) must appear letter-spaced in
    rewrite: `A. P. I.` for `API`, `H. T. T. P. S.` for `HTTPS`.

    Ship gate: score ≥ 0.95.
    """
    src_acronyms = set(_ACRONYM_PAT.findall(source))
    if not src_acronyms:
        return ScorerResult("acronym_letter_spacing", True, 1.0,
                            {"total": 0, "unspaced": []})
    unspaced = []
    for a in src_acronyms:
        # Expected letter-spaced form: "A. B. C."
        expected = ". ".join(list(a)) + "."
        # Also accept "A B C" (spaces without periods) — LLMs vary.
        expected_ns = " ".join(list(a))
        if expected in rewrite:
            continue
        if expected_ns in rewrite:
            continue
        # If the acronym appears verbatim (unspaced) → fail this one.
        if re.search(rf"\b{re.escape(a)}\b", rewrite):
            unspaced.append(a)
    total = len(src_acronyms)
    score = 1.0 - (len(unspaced) / total)
    return ScorerResult(
        "acronym_letter_spacing",
        passed=score >= 0.95,
        score=round(score, 3),
        details={"total": total, "unspaced": unspaced},
    )


# ── Forbidden punctuation ────────────────────────────────────────────

# Post-B-26 the AUDIO_REWRITE prompt allows `...`, `:`, `—` but still
# forbids `;`, `(`, `)`. Semicolons trip Kokoro; parentheticals never
# read well aloud.
_FORBIDDEN = ("(", ")", ";")


def forbidden_punctuation(rewrite: str) -> ScorerResult:
    """
    Forbid `;`, `(`, `)`. Ship gate: count == 0.
    """
    counts = {p: rewrite.count(p) for p in _FORBIDDEN}
    total = sum(counts.values())
    return ScorerResult(
        "forbidden_punctuation",
        passed=total == 0,
        score=1.0 if total == 0 else max(0.0, 1.0 - (total / 20)),
        details={"counts": counts},
    )


# ── Sentence-length distribution ─────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentence_length_dist(rewrite: str) -> ScorerResult:
    """
    Target: p50 sentence length ∈ [12, 20] words, p90 ≤ 25.

    Ship gate: passed if both conditions hold.
    """
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(rewrite) if s.strip()]
    if not sentences:
        return ScorerResult("sentence_length_dist", False, 0.0,
                            {"reason": "no_sentences"})
    lengths = sorted(len(s.split()) for s in sentences)
    n = len(lengths)
    p50 = lengths[n // 2]
    p90 = lengths[min(n - 1, int(0.9 * n))]
    passed = 12 <= p50 <= 20 and p90 <= 25
    # Score: 1.0 if in-band; degrades linearly with how far off.
    if passed:
        score = 1.0
    else:
        p50_penalty = max(0, 12 - p50) + max(0, p50 - 20)
        p90_penalty = max(0, p90 - 25)
        score = max(0.0, 1.0 - (p50_penalty + p90_penalty) / 30)
    return ScorerResult(
        "sentence_length_dist",
        passed=passed,
        score=round(score, 3),
        details={"n": n, "p50": p50, "p90": p90},
    )


# ── Attribution presence ────────────────────────────────────────────

def attribution_present(rewrite: str, source_name: str) -> ScorerResult:
    """
    Source name should appear in the first three sentences.
    Case-insensitive substring match — models often reformat but not
    remove.

    Ship gate: passed if source_name is present in first-3-sentence
    window.
    """
    if not source_name:
        return ScorerResult("attribution_present", True, 1.0,
                            {"reason": "no_source_name"})
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(rewrite) if s.strip()]
    window = " ".join(sentences[:3]).lower()
    hit = source_name.lower() in window
    return ScorerResult(
        "attribution_present",
        passed=hit,
        score=1.0 if hit else 0.0,
        details={"source_name": source_name, "in_first_3_sentences": hit},
    )


# ── Batch driver ────────────────────────────────────────────────────

def run_all(source: str, rewrite: str, source_name: str = "") -> list[ScorerResult]:
    """Run all five scorers; return list. Caller decides all-must-pass."""
    return [
        numeric_preservation(source, rewrite),
        acronym_letter_spacing(source, rewrite),
        forbidden_punctuation(rewrite),
        sentence_length_dist(rewrite),
        attribution_present(rewrite, source_name),
    ]


def all_passed(results: list[ScorerResult]) -> bool:
    return all(r.passed for r in results)


if __name__ == "__main__":
    # Smoke test with a synthetic rewrite.
    src = "Reuters reports that the Fed cut rates by 0.25%, the API price fell $40M."
    good = ("Reuters reports that the Fed cut rates by zero point two five percent. "
            "The A. P. I. price fell forty million dollars.")
    bad = ("The Fed cut rates. Prices dropped a lot. API prices fell $40M. "
           "Rates changed (unexpectedly); this matters.")
    print("Good rewrite:")
    for r in run_all(src, good, "Reuters"):
        print(f"  {r.name}: passed={r.passed} score={r.score} {r.details}")
    print("\nBad rewrite:")
    for r in run_all(src, bad, "Reuters"):
        print(f"  {r.name}: passed={r.passed} score={r.score} {r.details}")
