"""Dedup candidates against each other and against recently-published stories."""
from __future__ import annotations
import json
from pathlib import Path
from sentence_transformers import SentenceTransformer, util
from . import config

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def _published_titles(days: int = 3) -> list[str]:
    if not config.MANIFEST_PATH.exists():
        return []
    data = json.loads(config.MANIFEST_PATH.read_text())
    return [s["title"] for s in data.get("stories", [])][:100]


def dedup(titles: list[str]) -> list[int]:
    """Return indices of titles to keep (drops near-duplicates)."""
    if not titles:
        return []
    model = _get_model()
    published = _published_titles()
    all_titles = titles + published
    embs = model.encode(all_titles, convert_to_tensor=True, normalize_embeddings=True)
    new_embs = embs[: len(titles)]
    pub_embs = embs[len(titles):]

    keep: list[int] = []
    kept_embs = []
    for i, emb in enumerate(new_embs):
        if len(pub_embs) > 0:
            sim_pub = util.cos_sim(emb, pub_embs).max().item()
            if sim_pub >= config.DEDUP_THRESHOLD:
                continue
        if kept_embs:
            import torch
            stacked = torch.stack(kept_embs)
            sim_new = util.cos_sim(emb, stacked).max().item()
            if sim_new >= config.DEDUP_THRESHOLD:
                continue
        keep.append(i)
        kept_embs.append(emb)
    return keep
