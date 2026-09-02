"""Multi-source ingestion package.

Each source module exposes a `fetch(config)` function that returns a list of
Candidate objects. The registry loads sources.yaml and dispatches by type.
"""
from .base import Candidate
from .registry import fetch_all

__all__ = ["Candidate", "fetch_all"]
