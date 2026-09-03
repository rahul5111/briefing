"""Classify each story into {main, sub} per PLAN.md § 1.

Eight top-level categories, each with its own subcategory list. Every story
gets exactly one main and one sub. Ties broken by cross-category priority:

    Science > AI > Sports > Tech > Business > US > India > World

If US or India tags apply strongly, prefer them over generic World.

Emits back-compat fields:
- `category`: mirrors `main` (used by existing UI/tests until they migrate)
- `subcategory`: same as `sub`
- `main`, `sub`: canonical fields going forward
"""
from __future__ import annotations
import json
import re
from typing import Iterable, TypedDict
from google import genai

from . import config


TAXONOMY: dict[str, list[str]] = {
    "AI": [
        "Models & Research",
        "Products & Tools",
        "Infrastructure",
        "Policy & Safety",
        "Industry",
    ],
    "TECH": [
        "Software & Open Source",
        "Startups",
        "Consumer Tech",
        "Enterprise & Cloud",
        "Security & Privacy",
        "Gaming",
    ],
    "SCIENCE": [
        "Space & Physics",
        "Biology & Medicine",
        "Climate & Environment",
        "Materials & Chemistry",
        "Engineering & Robotics",
        "Awards & Patents",
    ],
    "SPORTS": [
        "Major Events",
        "Badminton",
        "Track & Field",
        "Cricket",
        "Tennis",
        "Cycling",
        "Boxing & MMA",
        "Marathons & Endurance",
        "Motorsport",
        "Soccer",
        "Basketball",
        "Golf",
        "Other",
    ],
    "US": [
        "Politics",
        "Economy",
        "Law & Courts",
        "Health",
        "Disasters",
        "Policy Changes",
        "Society",
    ],
    "INDIA": [
        "Politics",
        "Economy",
        "Law & Courts",
        "Health",
        "Disasters",
        "Policy Changes",
        "Society",
        "Foreign Relations",
    ],
    "WORLD": [
        "Politics & Elections",
        "Conflict & Security",
        "Economy & Trade",
        "Climate & Disasters",
        "Society & Culture",
        "Health & Public Policy",
    ],
    "BUSINESS": [
        "M&A & Deals",
        "Markets & IPOs",
        "Leadership & Layoffs",
        "Finance & Fintech",
        "Antitrust & Regulation",
        "Retail & Consumer",
    ],
}

MAIN_CATEGORIES = list(TAXONOMY.keys())

# Cross-category tie-break priority (PLAN.md § 1).
PRIORITY = ["SCIENCE", "AI", "SPORTS", "TECH", "BUSINESS", "US", "INDIA", "WORLD"]


class Label(TypedDict):
    main: str
    sub: str


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _format_taxonomy_for_prompt() -> str:
    lines = []
    for main, subs in TAXONOMY.items():
        lines.append(f"- {main}: {', '.join(subs)}")
    return "\n".join(lines)


SINGLE_PROMPT = """Classify this news story into ONE (main, sub) pair from the taxonomy below.

Taxonomy (main → allowed subs):
{taxonomy}

Cross-category priority when a story straddles: Science > AI > Sports > Tech > Business > US > India > World.
If a story is primarily about US politics/economy/law, use US (not World). Same for India.

Return ONE JSON object exactly like: {{"main": "AI", "sub": "Models & Research"}}.
No prose, no code fences.

Headline: {title}
Domain: {domain}
Short summary: {summary}
"""


BATCH_PROMPT = """Classify each story below into ONE (main, sub) pair from the taxonomy.

Taxonomy (main → allowed subs):
{taxonomy}

Cross-category priority when a story straddles: Science > AI > Sports > Tech > Business > US > India > World.
Prefer US or India over World when the story is primarily domestic to those countries.

Return a JSON array of {{"main":"...","sub":"..."}} objects, one per story, in order.
No prose, no code fences.

Stories:
{list}
"""


def _valid(pair: dict) -> Label | None:
    if not isinstance(pair, dict):
        return None
    main = str(pair.get("main", "")).strip().upper()
    sub = str(pair.get("sub", "")).strip()
    if main not in TAXONOMY:
        return None
    # Case-insensitive sub match (LLMs sometimes drop the ampersand or spacing).
    for allowed in TAXONOMY[main]:
        if sub.lower() == allowed.lower():
            return {"main": main, "sub": allowed}
    # Sub not recognised: bucket to first sub as a safe default.
    return {"main": main, "sub": TAXONOMY[main][0]}


_FALLBACK: Label = {"main": "WORLD", "sub": "Society & Culture"}


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


def _parse_json_array(raw: str) -> list | None:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def classify_one(title: str, summary: str, domain: str = "") -> Label:
    client = _get_client()
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=SINGLE_PROMPT.format(
            taxonomy=_format_taxonomy_for_prompt(),
            title=title,
            domain=domain,
            summary=summary[:400],
        ),
        config={"temperature": 0.0, "max_output_tokens": 80},
    )
    parsed = _parse_json_object(resp.text or "")
    return _valid(parsed) or _FALLBACK


def classify_batch(items: Iterable[dict]) -> list[Label]:
    """Classify many stories in a single LLM call.

    Each item: {"title": str, "domain": str, "summary": Optional[str]}
    """
    items = list(items)
    if not items:
        return []
    lines = []
    for i, it in enumerate(items, 1):
        summary = it.get("summary", "") or ""
        line = f"{i}. [{it.get('domain','')}] {it['title']}"
        if summary:
            line += f"  ({summary[:180].strip()})"
        lines.append(line)
    prompt = BATCH_PROMPT.format(
        taxonomy=_format_taxonomy_for_prompt(),
        list="\n".join(lines),
    )
    client = _get_client()
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config={"temperature": 0.0, "max_output_tokens": 40 * len(items) + 200},
    )
    arr = _parse_json_array(resp.text or "") or []
    out: list[Label] = []
    for x in arr:
        out.append(_valid(x) or _FALLBACK)
    while len(out) < len(items):
        out.append(_FALLBACK)
    return out[: len(items)]


# ─── Back-compat shim ─────────────────────────────────────────────
# Old callers expected `list[str]` (main category only). Preserve that
# signature under a legacy name so nothing breaks if a call site still
# uses it.
def classify_batch_legacy(items: Iterable[dict]) -> list[str]:
    return [lbl["main"] for lbl in classify_batch(items)]
