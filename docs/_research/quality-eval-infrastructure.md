# Quality-Enhancement & Evaluation Infrastructure — Research Memo

**Date:** 2026-09-14
**Scope:** Smallest, cheapest, checked-into-repo evaluation and monitoring
that meaningfully catches regressions on the Briefing cron. Answers the
gaps flagged in `docs/architecture-overview.md` §17, §19-6, §19-15 and
refines the shadow-mode workflow sketched in
`docs/design-review-2026-09-14.md` §17.

Guiding constraints: single-user Python cron, no external dashboards,
all artefacts committed to the repo, must fail loud in workflow logs.

---

## 1. Filter drift detection

**Recommendation: rolling median + IQR band, not KL, not fixed thresholds.**

KL divergence on category distributions is theoretically clean but noisy
at N ≈ 100 stories/day — small categories (SCIENCE, INDIA) will swing KL
just from sampling variance and cause false alarms. Fixed thresholds
(accept < 20% or > 60%) are legitimate but coarse; they miss slow drift
where a filter change moves the mean from 42% to 28% over a week without
ever tripping.

The right primitive is a rolling median with an IQR-scaled band, computed
against the last 7 days of `data/rejections/YYYY-MM-DD.jsonl` +
manifest-in cardinality. This is robust to a single freakish day and
degrades gracefully when the history is short.

```python
# pipeline/drift.py (proposed)
from pathlib import Path
import json, statistics, datetime as dt, sys
from pipeline import config

def compute_drift(today: dt.date) -> dict:
    hist = []                                # last 7 completed days
    for d in (today - dt.timedelta(days=i) for i in range(1, 8)):
        rec = _load_day(d)                   # {accept, reject, dedup, in}
        if rec: hist.append(rec)
    today_rec = _load_day(today)             # today, computed live
    if len(hist) < 4 or not today_rec:
        return {"status": "warmup", "history_days": len(hist)}

    rates = [h["accept"] / max(h["in"], 1) for h in hist]
    med = statistics.median(rates)
    q1, q3 = statistics.quantiles(rates, n=4)[0], statistics.quantiles(rates, n=4)[2]
    iqr = max(q3 - q1, 0.03)                 # floor to avoid div-by-zero
    today_rate = today_rec["accept"] / max(today_rec["in"], 1)
    z = (today_rate - med) / iqr

    status = "ok"
    if abs(z) > 2.5:      status = "breach"
    elif abs(z) > 1.5:    status = "warn"
    # Hard floor / ceiling always fire regardless of history:
    if today_rate < 0.10 or today_rate > 0.70: status = "breach"

    out = {"date": str(today), "today_rate": today_rate,
           "median_7d": med, "iqr": iqr, "z": z, "status": status,
           "counts": today_rec}
    Path(config.ROOT / "data/drift").mkdir(parents=True, exist_ok=True)
    (config.ROOT / f"data/drift/{today}.json").write_text(json.dumps(out, indent=2))
    if status == "breach":
        sys.exit(2)                          # fails the workflow
    return out
```

Wire it into `run.py` immediately after `significance.write_rejection_log`
so today's counts exist before the check. Warmup (< 4 history days)
short-circuits so bootstrap doesn't false-fire.

---

## 2. Golden evaluation set

**Store:** `pipeline/eval/golden_set.jsonl` — one JSON object per line so
diffs are legible in PR review.

**Schema per row:**

```json
{
  "id": "golden-0007",
  "source": "reuters",
  "url": "...",
  "title": "...",
  "body_snippet": "first 800 chars",           // enough to score without fetching
  "expected": {
    "main": "WORLD",                            // top-level category
    "sub": "geopolitics",
    "importance": "high",                       // low|medium|high|critical
    "score_band": [0.55, 0.85],                 // significance_v2 range
    "story_type": "developing",                 // developing|explainer|announcement|analysis
    "cluster_hint": "gaza-ceasefire-2026-09",   // freeform slug, optional
    "should_reject": false,
    "reject_reason": null
  },
  "notes": "policy: WORLD floor must keep this"
}
```

30 stories baseline, 50 stretch. Mix: 20 clear-accept (band checks),
5 clear-reject (must-drop noise), 5 boundary cases (score_band width
0.15 to catch tuning drift), plus 5 cluster-hint pairs to test dedup.

**Runner:** `python -m pipeline.eval.run_golden` — imports the live
`significance.score`, `categorize.classify`, `dedup.match` and asserts:

- `main` exact match → category-agreement %
- `score` falls inside `score_band` → band-agreement %
- reject/accept decision matches `should_reject` → decision-agreement %
- cluster_hint matches present among same-hint pair → cluster-agreement %

Writes `data/eval/golden_YYYY-MM-DD.json` and exits non-zero when
category-agreement < 85%, band-agreement < 80%, or decision-agreement < 90%.
Runs on every cron and every PR that touches `significance.py`,
`categorize.py`, or their prompts.

---

## 3. Per-run health dashboard

Regenerated each cron at `data/health/latest.md` (overwrite; the JSONL
history lives elsewhere). Markdown so the owner reads it in-browser
on the repo. Schema:

```
# Briefing run — 2026-09-14T06:12Z

## Intake
- candidates_in: 512
- accepted: 118 (23.0 %)     [7-day median 24.1 %, z=−0.4]
- rejected: 394
  - by-reason: significance=310, dedup=61, blocklist=18, malformed=5

## Content pipeline
- dedup_matches: 61
- refine_stories: 118  (avg latency 4.2 s)
- gemini_calls: 894    (est. $0.71)

## Audio
- tts_generated: 118
- whisper_wer:
    p50=0.041  p90=0.087  p99=0.152
    fail_gate (>0.10): 12   (10.2 %)
    voices:  am_liam=0.045  am_michael=0.061

## Run
- start: 06:11:07Z
- end:   06:47:22Z
- duration: 36m 15s
- exit: 0
- drift_status: ok
- golden_eval: pass (cat=94%, band=87%, decision=93%)
```

Machine-readable twin at `data/health/latest.json` for the golden runner
and drift detector to consume without regexing markdown.

---

## 4. WER regression tracking

**Row store:** `data/audio_wer_history.jsonl`. Append-only, one line per
story per generation. Schema:

```json
{"date":"2026-09-14","story_id":"...","voice":"am_liam",
 "category":"WORLD","story_type":"developing","duration_s":124.3,
 "wer":0.062,"cer":0.031,"subs":[["gaza","gasa"]],"gate":"pass"}
```

`audio_validate.py` already computes the per-story fields — the delta is
just append-write to the history file.

**Weekly summary:** `python -m pipeline.eval.wer_weekly` runs each
Sunday cron, buckets last 7 days by `voice`, `category`, `story_type`,
computes p50/p90 per bucket, and flags any bucket where p90 crosses
0.12 or p50 shifts more than +0.02 vs the prior week. Writes
`data/health/wer_weekly_YYYY-WW.md` and pins the latest as
`data/health/wer_weekly_latest.md`. Non-zero exit on any red bucket so
the failing run is visible in GHA history.

---

## 5. Regression guard for significance rebuild

Concrete week-by-week workflow, refining the design-review §17 sketch:

**Day 0 (branch open).** Add `significance_v3.py` alongside v2. Both
run in `run.py`; only v2 gates the manifest. Every story gets both
`score_v2` and `score_v3` written. `python -m pipeline.eval.shadow_diff`
runs after every cron, emits `data/eval/shadow_YYYY-MM-DD.json`:

- correlation(score_v2, score_v3)
- disagreement rate: |band(v2) ≠ band(v3)|
- golden-set: how many of 30–50 verdicts differ

**Days 1–7 (shadow).** Owner reviews `shadow_*.json` daily. Merge blocks
if any of:
- accept-rate under v3 would drop > 30% vs v2 (7-day median),
- ≥ 10 golden verdicts diverge on category or decision,
- pearson(v2, v3) < 0.6 (v3 is a different animal, not an improvement).

**Day 7 (flip).** Once three consecutive daily shadow reports are green,
flip the gate to v3. v2 still computes and writes `score_v2` for
comparison — do not delete.

**Days 7–14 (canary).** Drift detector (§1) runs against v3. Golden
runner (§2) runs against v3. Any breach or golden drop reverts the flip
via a single-line change; v2 is still there.

**Day 14 (retire).** Remove v2 code + `score_v2` writes. Keep the last
week's shadow diffs under `data/eval/shadow_archive/` for postmortem
memory. Total added retention: ~2 KB × 14 files.

---

## 6. Categorization second-pass (temperature consensus)

**Verdict: worth prototyping, low value in isolation, high value paired
with the golden set.**

Doubling `categorize.classify` calls (T=0.0 and T=0.3) costs pennies at
current volume (~$0.05/day extra). Two failure modes it plausibly
catches: (a) borderline TECH vs SCIENCE splits where the prompt is
underspecified, (b) rare-topic hallucinations where T=0.3 wanders.

But without a labelled set, "flag for review" becomes "another JSONL
nobody reads." The value only materialises when disagreements are
scored against `golden_set.jsonl` — otherwise it's ceremony.

**Proposal:** ship consensus categorization only after the golden set
exists (§2). Log disagreements to `data/eval/categorize_disagreements.jsonl`
and require the golden runner to include a "how often does consensus
match the golden label vs single-shot?" metric. If consensus gains
< 2 pp of category-agreement, drop it. If it gains ≥ 5 pp, keep it as
the default path.

---

## Priority order for the owner

1. §3 health markdown (1 evening; unlocks everything else).
2. §1 drift detector (half a day; catches the loudest class of bug).
3. §4 WER history append (small delta on `audio_validate.py`).
4. §2 golden set (2–3 evenings of hand-labelling; hardest but highest ROI).
5. §5 shadow workflow (only when significance_v3 is actually drafted).
6. §6 consensus categorization (last; needs §2 to justify itself).

Word count: ~940.
