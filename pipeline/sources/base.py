"""Common types for source adapters."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Candidate:
    """One item pulled from a source, normalized for the refinement pipeline.

    `id` must be globally unique across sources — adapters prefix with their
    source name (e.g. "hn-49537553", "rss-verge-abc123", "reddit-r_prog-xyz").

    `text` is optional pre-fetched body (e.g. HN Ask posts, RSS content: encoded
    that includes the full article). If absent, downstream extraction fetches
    `url`.
    """
    id: str
    source: str                 # source name from config: "hackernews", "verge", ...
    title: str
    url: str | None
    text: str | None
    author: str
    created_at_ts: int          # unix epoch seconds
    score: int                  # source-specific popularity signal
    permalink: str              # link back to the source item (for attribution)
    extra: dict = field(default_factory=dict)
