"""Assign each story to one of a fixed set of categories.

Categories were chosen for a general tech/world briefing audience:

  AI        — LLMs, models, ML research, agentic tools, AI products
  STARTUPS  — funding, product launches, YC, acquisitions, company news
  SECURITY  — breaches, CVEs, exploits, malware, incident response
  DEV       — frameworks, languages, editors, CLIs, databases, infra
  RESEARCH  — papers, scientific findings, non-AI academic work
  WORLD     — geopolitics, economics, courts, government, human interest

Uses one cheap LLM call per story. Can also batch a whole feed at once, which
is what we do to backfill the existing manifest.
"""
from __future__ import annotations
import json
import re
from typing import Iterable
from google import genai

from . import config


CATEGORIES = ["AI", "STARTUPS", "SECURITY", "DEV", "RESEARCH", "WORLD"]

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


SINGLE_PROMPT = """Classify this news story into ONE category from this list:

- AI: large language models, AI research, agentic tools, AI products
- STARTUPS: funding rounds, product launches, YC, acquisitions, company news that is not primarily about the underlying tech
- SECURITY: breaches, CVEs, exploits, malware, incident response
- DEV: frameworks, programming languages, editors, CLIs, databases, infra, developer tooling
- RESEARCH: scientific papers or findings that are NOT primarily about AI
- WORLD: geopolitics, economics, courts, government, regulation, human interest

Return ONLY the category name, uppercase, nothing else.

Headline: {title}
Domain: {domain}
Short summary: {summary}
"""


def classify_one(title: str, summary: str, domain: str = "") -> str:
    client = _get_client()
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=SINGLE_PROMPT.format(title=title, summary=summary[:400], domain=domain),
        config={"temperature": 0.0, "max_output_tokens": 20},
    )
    out = (resp.text or "").strip().upper()
    for c in CATEGORIES:
        if c in out:
            return c
    return "DEV"  # safe fallback


BATCH_PROMPT = """Classify each story below into ONE category from this list:

- AI: LLMs, AI research, agentic tools, AI products
- STARTUPS: funding, launches, YC, acquisitions, company news
- SECURITY: breaches, CVEs, exploits, malware, incident response
- DEV: frameworks, languages, editors, CLIs, databases, infra, dev tooling
- RESEARCH: scientific papers or findings NOT primarily about AI
- WORLD: geopolitics, economics, courts, government, regulation, human interest

Return a JSON array with one category per story in the same order. Uppercase.
Only the array, no code fences, no other text.

Stories:
{list}
"""


def classify_batch(items: Iterable[dict]) -> list[str]:
    items = list(items)
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. [{it.get('domain','')}] {it['title']}")
    prompt = BATCH_PROMPT.format(list="\n".join(lines))
    client = _get_client()
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config={"temperature": 0.0, "max_output_tokens": 400},
    )
    raw = (resp.text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return ["DEV"] * len(items)
    try:
        arr = json.loads(m.group(0))
        out: list[str] = []
        for x in arr:
            up = str(x).strip().upper()
            out.append(up if up in CATEGORIES else "DEV")
        while len(out) < len(items):
            out.append("DEV")
        return out[: len(items)]
    except json.JSONDecodeError:
        return ["DEV"] * len(items)
