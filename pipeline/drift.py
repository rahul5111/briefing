"""B-35 filter drift detector — INFORMATIONAL ONLY.

Rolling 7-day median accept-rate + IQR-scaled z-score. Writes
`data/drift/YYYY-MM-DD.json`. **Never** fails the workflow — per
external-panel review, scalar accept-rate has 5–15 % false-alarm rate
baked in from calendar/weekend/source variance. Value surfaces in
the health dashboard; workflow exit is not gated on this.

Future upgrade (P1, BACKLOG B-70): replace scalar accept-rate with
score-distribution KS-test or binned-histogram delta.
"""
from __future__ import annotations
import json
import statistics
import datetime as dt
from pathlib import Path
from typing import Optional

# `data/drift/` is git-ignored per BACKLOG B-34. Written every run so
# the health dashboard has fresh input; not persisted.
_ROOT = Path(__file__).resolve().parent.parent
_DRIFT_DIR = _ROOT / "data" / "drift"


def _load_day(d: dt.date) -> Optional[dict]:
    """Read a persisted daily summary if it exists."""
    p = _DRIFT_DIR / f"{d.isoformat()}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def compute_drift(counts: dict, today: Optional[dt.date] = None) -> dict:
    """
    Compute today's accept-rate + IQR z-score against the last 7 days.

    `counts` is the per-run intake snapshot:
        {"in": <int>, "accept": <int>, "reject": <int>, "dedup": <int>}

    Returns a dict with the status, rate, band, and z-score. Writes
    the result to `data/drift/YYYY-MM-DD.json`. NEVER exits non-zero.
    """
    today = today or dt.date.today()

    hist: list[dict] = []
    for i in range(1, 8):
        rec = _load_day(today - dt.timedelta(days=i))
        if rec and "counts" in rec:
            hist.append(rec["counts"])

    n_in = max(counts.get("in", 0), 1)
    today_rate = counts.get("accept", 0) / n_in

    result: dict = {
        "date": today.isoformat(),
        "counts": counts,
        "today_rate": round(today_rate, 4),
        "history_days": len(hist),
    }

    if len(hist) < 4:
        # Warmup — insufficient history for a stable median.
        result["status"] = "warmup"
        result["message"] = f"warmup: only {len(hist)} history days"
        _write(today, result)
        return result

    rates = [h["accept"] / max(h["in"], 1) for h in hist]
    med = statistics.median(rates)

    # IQR via quantiles(n=4); guard for tiny samples.
    try:
        q1 = statistics.quantiles(rates, n=4)[0]
        q3 = statistics.quantiles(rates, n=4)[2]
        iqr = max(q3 - q1, 0.03)
    except statistics.StatisticsError:
        iqr = 0.03

    z = (today_rate - med) / iqr

    status = "ok"
    if abs(z) > 2.5:
        status = "breach"
    elif abs(z) > 1.5:
        status = "warn"

    # Hard-floor / ceiling always trip regardless of history width — these
    # are the numbers that mean "the pipeline is not doing what we want",
    # not "today looks unusual."
    if today_rate < 0.10 or today_rate > 0.70:
        status = "breach"

    result.update(
        {
            "median_7d": round(med, 4),
            "iqr": round(iqr, 4),
            "z": round(z, 3),
            "status": status,
        }
    )
    _write(today, result)
    return result


def _write(day: dt.date, result: dict) -> None:
    """Best-effort persistence. Failure must never fail the pipeline."""
    try:
        _DRIFT_DIR.mkdir(parents=True, exist_ok=True)
        (_DRIFT_DIR / f"{day.isoformat()}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False)
        )
    except Exception:
        pass


def summarise_line(result: dict) -> str:
    """One-line rendering for the health dashboard."""
    if result.get("status") == "warmup":
        return (
            f"drift: today {result.get('today_rate', 0) * 100:.1f}% · "
            f"warmup ({result.get('history_days', 0)} history days)"
        )
    rate = result.get("today_rate", 0) * 100
    med = result.get("median_7d", 0) * 100
    z = result.get("z", 0)
    status = result.get("status", "?")
    return (
        f"drift: today {rate:.1f}% · 7d-median {med:.1f}% · z={z:+.2f} · "
        f"status={status}"
    )


if __name__ == "__main__":
    # Manual invocation for testing.
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # Synthetic warmup case.
        r = compute_drift({"in": 500, "accept": 118, "reject": 380, "dedup": 2})
        print(summarise_line(r))
