"""Pronunciation normalization for TTS.

Runs AFTER the LLM audio-rewrite pass, as a safety net for anything the LLM
missed. Kokoro (and most neural TTS) mangles version numbers, dates, currency,
and acronyms. This module converts them into spoken form.

Rules are conservative — only fires when confident. When in doubt, leaves the
text alone rather than risk garbling a proper noun.
"""
from __future__ import annotations
import re
from num2words import num2words


# Acronyms we always spell out letter-by-letter. Kokoro reads NBA as "nubba"
# and IPL as "ipple" if we let it — the letter-spaced form ("N. B. A.") is
# read correctly. Order-agnostic set; matched case-sensitively via a
# whole-word regex in normalize() below.
SPELL_OUT = {
    # tech / product
    "AI", "API", "ML", "LLM", "CPU", "GPU", "TPU", "SDK", "CLI", "URL", "SQL",
    "HTTP", "HTTPS", "CSS", "HTML", "JSON", "XML", "YAML", "AWS", "GCP", "IBM",
    "NASA", "USB", "iOS", "OS", "OSS", "RAG", "RSS", "PDF", "PNG", "JPG",
    "MP3", "MP4", "RSC", "SSR", "SSG", "TLS", "SSL", "SSH", "DNS", "CDN",
    "VPN", "VPS", "ONNX", "CUDA", "ROCm",
    # US agencies + political
    "FBI", "CIA", "NSA", "DOJ", "DOD", "TSA", "ICE", "DEA", "ATF", "USSS",
    "SEC", "IRS", "FDA", "CDC", "FEMA", "EPA", "FTC", "FCC", "USDA", "HHS",
    "GAO", "CBO", "OMB", "SCOTUS", "GOP", "DNC", "RNC",
    # business / finance
    "IPO", "CEO", "CFO", "CTO", "COO", "CMO", "CIO", "VP", "MBA", "PhD",
    "USA", "UK", "EU", "UN", "NATO", "WHO", "GDP", "IMF", "WTO", "OPEC",
    "BRICS", "G7", "G20", "PE", "VC", "M&A", "AUM", "EBITDA", "APR", "APY",
    # sports (biggest cause of mispronunciation in the current feed)
    "NBA", "NFL", "NHL", "MLB", "MLS", "NCAA", "FIFA", "UEFA", "IOC", "WWE",
    "UFC", "PGA", "LPGA", "USGA", "ATP", "WTA", "BWF", "IPL", "ODI", "T20",
    "IPL", "BCCI", "WBC", "WBO", "IBF", "WBA",
    # india-specific (about to start appearing with the new sources)
    "RBI", "GST", "SEBI", "ISRO", "DRDO", "NITI", "CBI", "ED", "PMO", "CM",
    "MLA", "MP", "BJP", "INC", "AAP", "SP", "BSP", "PIB",
    # scientific orgs
    "ESA", "JAXA", "NOAA", "CERN", "JPL", "NIH", "NSF",
}

# Common abbreviations that should be expanded (spoken versions)
ABBREVIATIONS = [
    (r"(?i)\be\.g\.",   "for example"),
    (r"(?i)\bi\.e\.",   "that is"),
    (r"\betc\.?\b",     "and so on"),
    (r"\bvs\.?\b",    "versus"),
    (r"\bapprox\.", "approximately"),
    (r"\best\.",    "established"),
    (r"\best'd\b",    "established"),
    (r"\bavg\.",    "average"),
    (r"\bmin\.",    "minimum"),
    (r"\bmax\.",    "maximum"),
    (r"\bMr\.",     "Mister"),
    (r"\bMrs\.",    "Missus"),
    (r"\bMs\.",     "Miss"),
    (r"\bDr\.",     "Doctor"),
    (r"\bSt\.",     "Saint"),
    (r"\bJr\.",     "Junior"),
    (r"\bSr\.",     "Senior"),
    (r"\bU\.S\.",   "US"),
    (r"\bU\.K\.",   "UK"),
    (r"\bE\.U\.",   "EU"),
    (r"\bU\.N\.",   "UN"),
]

# Symbol replacements (spoken)
SYMBOLS = [
    ("&", " and "),
    ("+", " plus "),
    ("=", " equals "),
    ("%", " percent"),
    ("@", " at "),
    ("#", " number "),
    ("→", " to "),
    ("←", " from "),
    ("—", ", "),   # em-dash reads as pause
    ("–", ", "),   # en-dash reads as pause
]


def _num_to_words(n: int | float) -> str:
    try:
        return num2words(n)
    except Exception:
        return str(n)


def _year_to_words(y: int) -> str:
    """1997 → 'nineteen ninety-seven', 2026 → 'twenty twenty-six', 2005 → 'two thousand five'."""
    if 1000 <= y <= 2099:
        hi, lo = divmod(y, 100)
        if lo == 0:
            return num2words(y)                    # 1900 → "one thousand nine hundred"
        if hi in (19, 20) and lo < 10:
            # 2005 → "two thousand five", 1908 → "nineteen oh eight"
            if hi == 20:
                return f"two thousand {num2words(lo)}"
            return f"{num2words(hi)} oh {num2words(lo)}"
        return f"{num2words(hi)} {num2words(lo)}"
    return num2words(y)


def _expand_version(match: re.Match) -> str:
    """Version numbers: 3.8 → three point eight; 1.2.3 → one point two point three."""
    parts = match.group(0).split(".")
    return " point ".join(_num_to_words(int(p)) for p in parts)


def _expand_currency(match: re.Match) -> str:
    """$40M → forty million dollars; $1.2B → one point two billion dollars; $500 → five hundred dollars."""
    raw = match.group(0)
    sign = -1 if raw.startswith("-") else 1
    body = raw.lstrip("-$").replace(",", "")
    m = re.match(r"^(\d+(?:\.\d+)?)([KMBT])?$", body, re.IGNORECASE)
    if not m:
        return raw
    val = float(m.group(1))
    suffix = (m.group(2) or "").upper()
    scale = {"K": "thousand", "M": "million", "B": "billion", "T": "trillion"}.get(suffix, "")
    val_str = _num_to_words(int(val)) if val == int(val) else _decimal_to_words(val)
    parts = [val_str]
    if scale:
        parts.append(scale)
    parts.append("dollars")
    return ("negative " if sign < 0 else "") + " ".join(parts)


def _expand_percent(match: re.Match) -> str:
    """40% → forty percent; 3.5% → three point five percent."""
    raw = match.group(0).rstrip("%").strip()
    if "." in raw:
        return _decimal_to_words(float(raw)) + " percent"
    return _num_to_words(int(raw.replace(",", ""))) + " percent"


def _decimal_to_words(f: float) -> str:
    """3.14 → 'three point one four'."""
    s = str(f)
    if "." not in s:
        return _num_to_words(int(s))
    whole, frac = s.split(".")
    whole_w = _num_to_words(int(whole))
    frac_w = " ".join(_num_to_words(int(d)) for d in frac)
    return f"{whole_w} point {frac_w}"


def _expand_big_number(match: re.Match) -> str:
    """40,000 → forty thousand; 1,500,000 → one point five million (only when >= 1000)."""
    raw = match.group(0).replace(",", "")
    n = int(raw)
    if n < 1000:
        return match.group(0)
    return _num_to_words(n)


def _space_out_acronym(match: re.Match) -> str:
    """AI → A. I., API → A. P. I. — Kokoro reads letters with periods correctly."""
    word = match.group(0)
    if word in SPELL_OUT:
        return " ".join(list(word)) + "."
    return word


def _expand_year(match: re.Match) -> str:
    y = int(match.group(0))
    return _year_to_words(y)


def normalize(text: str) -> str:
    """Full pass: apply all normalizations in the right order."""
    if not text:
        return text

    t = text

    # 1. Strip stage-direction brackets and any markdown residue
    t = re.sub(r"[\*_`]+", "", t)
    t = re.sub(r"\[[^\]]*\]", "", t)

    # 2. Expand abbreviations first (before other regex touches them)
    for pat, repl in ABBREVIATIONS:
        t = re.sub(pat, repl, t)

    # 3. Currency: $40M, $1.2B, $500
    t = re.sub(r"-?\$\d+(?:\.\d+)?(?:,\d{3})*(?:[KMBT])?", _expand_currency, t, flags=re.IGNORECASE)

    # 4. Percentages: 40%, 3.5%
    t = re.sub(r"\d+(?:\.\d+)?(?:,\d{3})*%", _expand_percent, t)

    # 5. Years (1900-2099) as standalone 4-digit numbers
    t = re.sub(r"\b(19\d{2}|20\d{2})\b", _expand_year, t)

    # 6. Version numbers: 3.8, 1.2.3 (with a decimal point). Runs after year handling.
    t = re.sub(r"\b\d+(?:\.\d+){1,3}\b", _expand_version, t)

    # 7. Big numbers with commas: 40,000 → forty thousand
    t = re.sub(r"\b\d{1,3}(?:,\d{3})+\b", _expand_big_number, t)

    # 8. Symbols
    for sym, repl in SYMBOLS:
        t = t.replace(sym, repl)

    # 9. Spell-out acronyms — insert periods between letters so TTS reads them individually
    #    Only match words that are ALL CAPS and 2-5 letters
    def _acr(m: re.Match) -> str:
        return _space_out_acronym(m)
    t = re.sub(r"\b[A-Z]{2,5}\b", _acr, t)

    # 10. Clean up whitespace and stray commas — but PRESERVE paragraph breaks
    #     (blank line = \n\n) so tts.py can insert its longer 0.60s paragraph
    #     pauses. Collapsing all whitespace here used to destroy every
    #     paragraph in the input, turning every briefing into one flat blob
    #     with only 0.32s sentence gaps.
    t = re.sub(r"[ \t]+", " ", t)                         # collapse horizontal whitespace
    t = re.sub(r"[ \t]*\n[ \t]*\n[ \t\n]*", "\n\n", t)    # normalize any blank-line run to exactly one
    t = re.sub(r"(?<!\n)\n(?!\n)", " ", t)                # single newline → space
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",{2,}", ",", t)
    t = re.sub(r" +\.", ".", t)

    return t.strip()


if __name__ == "__main__":
    # Smoke test
    tests = [
        "Gemini 3.8 Flash launched in 2026 with a $40M investment.",
        "The API uses HTTPS and returns JSON. GDP grew 3.5% in Q2.",
        "Postgres 18 improves throughput by 15 to 40 percent.",
        "The FBI investigated 153,000,000 breaches in the U.S.",
        "e.g. Claude 4.7, i.e. the latest model, ships etc.",
    ]
    for t in tests:
        print(f"IN:  {t}")
        print(f"OUT: {normalize(t)}\n")
