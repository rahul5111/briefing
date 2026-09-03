"""Dedup candidates against each other and against recently-published stories.

Phase 2 groundwork (PLAN C1): while we still drop near-duplicates, we also
LOG every duplicate detection so we can observe whether the merge/synthesize
pipeline in C2+C3 would actually improve coverage before we build it.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from sentence_transformers import SentenceTransformer, util
from . import config

_model: SentenceTransformer | None = None


@dataclass
class DupHit:
    """One duplicate detection: `new_index` (into the input titles) matched
    something at `sim` similarity. `matched_kind` is 'published' when the
    match was against the manifest, or 'new' when against another candidate
    from the same batch."""

    new_index: int
    new_title: str
    matched_title: str
    matched_kind: str  # 'published' | 'new'
    sim: float


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
    """Legacy signature — return indices of titles to keep."""
    keep, _ = dedup_with_log(titles)
    return keep


def dedup_with_log(titles: list[str]) -> tuple[list[int], list[DupHit]]:
    """Return (indices_to_keep, duplicate_log)."""
    if not titles:
        return [], []
    model = _get_model()
    published = _published_titles()
    all_titles = titles + published
    embs = model.encode(all_titles, convert_to_tensor=True, normalize_embeddings=True)
    new_embs = embs[: len(titles)]
    pub_embs = embs[len(titles):]

    keep: list[int] = []
    kept_embs = []
    kept_indices: list[int] = []
    dup_log: list[DupHit] = []

    for i, emb in enumerate(new_embs):
        if len(pub_embs) > 0:
            sims = util.cos_sim(emb, pub_embs)[0]
            best = int(sims.argmax().item())
            best_sim = float(sims[best].item())
            if best_sim >= config.DEDUP_THRESHOLD:
                dup_log.append(DupHit(
                    new_index=i,
                    new_title=titles[i],
                    matched_title=published[best],
                    matched_kind="published",
                    sim=round(best_sim, 4),
                ))
                continue
        if kept_embs:
            import torch
            stacked = torch.stack(kept_embs)
            sims = util.cos_sim(emb, stacked)[0]
            best = int(sims.argmax().item())
            best_sim = float(sims[best].item())
            if best_sim >= config.DEDUP_THRESHOLD:
                dup_log.append(DupHit(
                    new_index=i,
                    new_title=titles[i],
                    matched_title=titles[kept_indices[best]],
                    matched_kind="new",
                    sim=round(best_sim, 4),
                ))
                continue
        keep.append(i)
        kept_embs.append(emb)
        kept_indices.append(i)
    return keep, dup_log


def write_dup_log(dup_log: list[DupHit], run_id: str | None = None) -> Path | None:
    """Append duplicate detections to data/duplicates/YYYY-MM-DD.jsonl for
    later observation. Returns the path written (or None if empty)."""
    if not dup_log:
        return None
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_dir = config.ROOT / "data" / "duplicates"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{day}.jsonl"
    run_ts = datetime.now(timezone.utc).isoformat()
    with path.open("a") as f:
        for hit in dup_log:
            row = asdict(hit)
            row["run_ts"] = run_ts
            if run_id:
                row["run_id"] = run_id
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
