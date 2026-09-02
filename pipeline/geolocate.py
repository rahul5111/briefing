"""Extract the primary geographic location of a story, if any.

Not every story has one — e.g. "PostgreSQL 18 released" is placeless, but
"Dutch central bank moves gold to London" clearly is about the Netherlands
and the UK. We use one cheap LLM call that returns either a location object
or null.

Kept coordinates in the LLM output means we avoid a separate geocoding hop —
the model knows the lat/lng of every major city.
"""
from __future__ import annotations
import json
import re
from typing import Iterable
from google import genai

from . import config


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


PROMPT = """For each news story below, return the most-relevant single geographic
location on Earth for that story, or null only if truly placeless.

Priority order for choosing:
1. A specific city or region named in the headline (e.g. "London", "Kenya's
   coast")
2. The country of the primary company, agency, court, or government mentioned
   (e.g. "FBI probes X" → United States, Washington DC coords; "Dutch central
   bank" → Netherlands, Amsterdam coords; "Mistral trains on user data" →
   France, Paris coords; "Anthropic ships model" → United States, San
   Francisco coords)
3. If the story is about a product, use the HQ of the maker.
4. Only return null for stories with no plausible geographic anchor at all —
   e.g. pure math papers, generic software how-tos, opinion posts without a
   company or place.

Prefer specific cities over broad countries when you can. Coordinates should
be reasonable lat/lng of the chosen place.

Return a JSON array of the same length, each item either null or:
  {{"name": "London", "country": "United Kingdom", "lat": 51.51, "lng": -0.13}}

Only the JSON array, no code fences, no other text.

Stories:
{list}
"""


def _extract_json(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    m = re.search(r"\[.*\]", s, re.S)
    return m.group(0) if m else s


def geolocate_batch(items: Iterable[dict]) -> list[dict | None]:
    items = list(items)
    if not items:
        return []
    lines = [f"{i+1}. [{it.get('domain','')}] {it['title']}" for i, it in enumerate(items)]
    prompt = PROMPT.format(list="\n".join(lines))
    client = _get_client()
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config={"temperature": 0.0, "max_output_tokens": 1200},
    )
    raw = (resp.text or "").strip()
    try:
        arr = json.loads(_extract_json(raw))
    except json.JSONDecodeError:
        return [None] * len(items)
    out: list[dict | None] = []
    for x in arr:
        if not isinstance(x, dict):
            out.append(None)
            continue
        try:
            out.append({
                "name": str(x["name"]),
                "country": str(x.get("country", "")),
                "lat": float(x["lat"]),
                "lng": float(x["lng"]),
            })
        except (KeyError, TypeError, ValueError):
            out.append(None)
    while len(out) < len(items):
        out.append(None)
    return out[: len(items)]
