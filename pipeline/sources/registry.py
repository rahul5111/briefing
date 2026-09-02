"""Load sources.yaml, dispatch to per-type adapters, return merged candidates.

The YAML config lives at pipeline/sources.yaml. Each entry needs:
  - name:    unique short slug (used as source label + id prefix)
  - type:    one of: hn | rss | reddit
  - enabled: bool (optional, default true)
  - ...:     type-specific config

Adding a new source type is:
  1. Create pipeline/sources/<type>.py with a `fetch(cfg) -> list[Candidate]`
  2. Register in ADAPTERS below
  3. Add an entry to sources.yaml
"""
from __future__ import annotations
from pathlib import Path
import yaml

from . import hn, rss, reddit
from .base import Candidate

ADAPTERS = {
    "hn": hn.fetch,
    "rss": rss.fetch,
    "reddit": reddit.fetch,
}

_CONFIG_PATH = Path(__file__).parent.parent / "sources.yaml"


def _load_config(path: Path | None = None) -> list[dict]:
    p = path or _CONFIG_PATH
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text()) or {}
    return data.get("sources") or []


def fetch_all(config_path: Path | None = None) -> list[Candidate]:
    sources = _load_config(config_path)
    all_candidates: list[Candidate] = []
    for cfg in sources:
        if not cfg.get("enabled", True):
            continue
        adapter = ADAPTERS.get(cfg.get("type"))
        if not adapter:
            print(f"  [{cfg.get('name','?')}] unknown type '{cfg.get('type')}', skipping")
            continue
        try:
            got = adapter(cfg)
        except Exception as e:
            print(f"  [{cfg.get('name','?')}] fetch failed: {e}")
            continue
        print(f"  [{cfg['name']:22s}] {len(got)} items")
        all_candidates.extend(got)
    all_candidates.sort(key=lambda c: c.score, reverse=True)
    return all_candidates
