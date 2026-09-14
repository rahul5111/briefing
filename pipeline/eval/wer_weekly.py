"""B-22 weekly WER summary.

Reads the last 7 days of data/audio_wer_history/*.jsonl. Buckets by
voice, category, story_type. Computes p50 and p90 per bucket. Flags
any bucket where p90 > 0.12 or where p50 shifted more than +0.02 vs
the prior week (regression).

Writes:
  data/health/wer_weekly_YYYY-WW.md   (dated, kept per week)
  data/health/wer_weekly_latest.md    (pointer to newest)

Exit codes:
  0 — no regressions
  2 — one or more red buckets — surfaces in GHA history but does NOT
      block the pipeline (observability, not correctness).

Usage:
  python -m pipeline.eval.wer_weekly
"""
from __future__ import annotations
import datetime as dt
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

_ROOT = Path(__file__).resolve().parent.parent.parent
_HISTORY_DIR = _ROOT / "data" / "audio_wer_history"
_HEALTH_DIR = _ROOT / "data" / "health"

_P90_ALARM = 0.12
_P50_SHIFT_ALARM = 0.02


def _rows_in_range(start: dt.date, end: dt.date) -> Iterable[dict]:
    """Iterate rows across possibly-multiple monthly files covering
    [start, end]."""
    if not _HISTORY_DIR.exists():
        return
    d = start
    while d <= end:
        month = d.strftime("%Y-%m")
        f = _HISTORY_DIR / f"{month}.jsonl"
        if f.exists():
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                try:
                    row_date = dt.date.fromisoformat(row.get("date", ""))
                except Exception:
                    continue
                if start <= row_date <= end:
                    yield row
        # advance one month worth
        if d.month == 12:
            d = d.replace(year=d.year + 1, month=1)
        else:
            d = d.replace(month=d.month + 1)


def _percentiles(values: list[float]) -> tuple[float, float]:
    """Return (p50, p90) with graceful fallback for small samples."""
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], values[0])
    vs = sorted(values)
    p50 = statistics.median(vs)
    # Simple percentile via nearest-rank.
    idx = min(len(vs) - 1, max(0, int(0.9 * (len(vs) - 1))))
    return (round(p50, 4), round(vs[idx], 4))


def bucket_rows(rows: Iterable[dict], key_fn) -> dict[str, list[float]]:
    """Group WER values by a key function."""
    out: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        wer = r.get("wer")
        if wer is None:
            continue
        k = key_fn(r) or "unknown"
        out[k].append(float(wer))
    return dict(out)


def _week_key(d: dt.date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def summarise(as_of: dt.date | None = None) -> tuple[dict, list[str]]:
    """
    Return (summary_dict, red_flags).
    """
    as_of = as_of or dt.date.today()
    this_end = as_of
    this_start = as_of - dt.timedelta(days=6)
    prev_end = this_start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=6)

    this_rows = list(_rows_in_range(this_start, this_end))
    prev_rows = list(_rows_in_range(prev_start, prev_end))

    result = {
        "week": _week_key(as_of),
        "range": {"start": this_start.isoformat(), "end": this_end.isoformat()},
        "n_this": len(this_rows),
        "n_prev": len(prev_rows),
        "by_voice": {},
        "by_category": {},
        "by_story_type": {},
    }
    red_flags: list[str] = []

    def _summarise_bucket(name: str, this_rows: Iterable[dict],
                          prev_rows: Iterable[dict], key_fn) -> dict:
        this_b = bucket_rows(this_rows, key_fn)
        prev_b = bucket_rows(prev_rows, key_fn)
        buckets: dict[str, dict] = {}
        for k, vals in sorted(this_b.items()):
            p50, p90 = _percentiles(vals)
            prev_vals = prev_b.get(k) or []
            prev_p50, _ = _percentiles(prev_vals) if prev_vals else (None, None)
            shift = None if prev_p50 is None else round(p50 - prev_p50, 4)
            status = "ok"
            if p90 > _P90_ALARM:
                status = "red"
                red_flags.append(f"{name}/{k}: p90={p90:.3f} > {_P90_ALARM}")
            if shift is not None and shift > _P50_SHIFT_ALARM:
                status = "red"
                red_flags.append(
                    f"{name}/{k}: p50 shift {shift:+.3f} > +{_P50_SHIFT_ALARM}"
                )
            buckets[k] = {
                "n": len(vals),
                "p50": p50,
                "p90": p90,
                "prev_p50": prev_p50,
                "shift": shift,
                "status": status,
            }
        return buckets

    result["by_voice"] = _summarise_bucket(
        "voice", this_rows, prev_rows, lambda r: r.get("voice", ""))
    result["by_category"] = _summarise_bucket(
        "category", this_rows, prev_rows, lambda r: r.get("category", ""))
    result["by_story_type"] = _summarise_bucket(
        "story_type", this_rows, prev_rows, lambda r: r.get("story_type", ""))

    return result, red_flags


def render_md(summary: dict, red_flags: list[str]) -> str:
    lines = [f"# WER weekly — {summary['week']}", ""]
    r = summary["range"]
    lines.append(f"Range: {r['start']} → {r['end']}")
    lines.append(f"Samples: this week {summary['n_this']}, prior {summary['n_prev']}")
    lines.append("")

    if red_flags:
        lines.append(f"## ⚠  {len(red_flags)} red bucket(s)")
        for f in red_flags:
            lines.append(f"- {f}")
        lines.append("")

    for section_key, section_title in [
        ("by_voice", "By voice"),
        ("by_category", "By category"),
        ("by_story_type", "By story_type"),
    ]:
        lines.append(f"## {section_title}")
        buckets = summary.get(section_key) or {}
        if not buckets:
            lines.append("_(no rows this week)_")
            lines.append("")
            continue
        lines.append("| bucket | n | p50 | p90 | prev p50 | shift | status |")
        lines.append("|---|---:|---:|---:|---:|---:|:-:|")
        for name, b in buckets.items():
            marker = "⚠" if b["status"] == "red" else " "
            lines.append(
                f"| {name} | {b['n']} | {b['p50']} | {b['p90']} | "
                f"{b.get('prev_p50', '—')} | {b.get('shift', '—')} | {marker} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    summary, red_flags = summarise()
    _HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    md = render_md(summary, red_flags)
    (_HEALTH_DIR / f"wer_weekly_{summary['week']}.md").write_text(md)
    (_HEALTH_DIR / "wer_weekly_latest.md").write_text(md)

    if red_flags:
        print(f"[wer_weekly] {len(red_flags)} red bucket(s):", file=sys.stderr)
        for f in red_flags:
            print(f"  - {f}", file=sys.stderr)
        return 2
    print(f"[wer_weekly] {summary['week']}: no regressions across "
          f"{len(summary['by_voice'])} voices, "
          f"{len(summary['by_category'])} categories, "
          f"{len(summary['by_story_type'])} story_types.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
