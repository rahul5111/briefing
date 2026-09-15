"""B-33 per-run health dashboard.

Regenerates `data/health/latest.md` and `data/health/latest.json` each
run. Both are git-ignored (BACKLOG B-34) — the markdown is for the
owner to glance at in-browser, the JSON is for the golden runner /
drift detector to consume without regexing markdown.

Design intent: this file MUST NOT fail the pipeline. Wrap the render
in try/except; on failure write a single `[health] failed at <ts>` line
to `latest.md` and continue.
"""
from __future__ import annotations
import json
import datetime as dt
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_HEALTH_DIR = _ROOT / "data" / "health"


def render(snapshot: dict[str, Any]) -> None:
    """
    Write `latest.md` and `latest.json` from a run snapshot.

    Expected snapshot shape (all keys optional; missing renders as '—'):
        {
          "run_id": "...",
          "started_at": "2026-09-14T06:11:07Z",
          "ended_at":   "2026-09-14T06:47:22Z",
          "duration_s": 2175,
          "exit": 0,

          "intake": {
              "candidates_in": 512,
              "accepted": 118,
              "rejected": 394,
              "reject_by_reason": {"significance": 310, "dedup": 61,
                                    "blocklist": 18, "malformed": 5},
              "dedup_matches": 61,
          },
          "refine": {
              "stories": 118,
              "avg_latency_s": 4.2,
              "gemini_calls": 894,
              "cost_estimate_usd": 0.71,
          },
          "audio": {
              "tts_generated": 118,
              "wer_p50": 0.041,
              "wer_p90": 0.087,
              "wer_p99": 0.152,
              "wer_fail_gate": 12,
              "per_voice": {"am_liam": 0.045, "am_michael": 0.061},
          },
          "storage": {
              "s3_uploads_ok": 118,
              "s3_uploads_failed": 0,
          },
          "drift": <output of pipeline.drift.compute_drift>,
          "golden": {"pass": true, "cat": 0.94, "band": 0.87,
                     "decision": 0.93, "n": 30},
        }
    """
    try:
        _HEALTH_DIR.mkdir(parents=True, exist_ok=True)
        (_HEALTH_DIR / "latest.md").write_text(_markdown(snapshot))
        (_HEALTH_DIR / "latest.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False, default=str)
        )
    except Exception as e:
        # Self-failure guard (external panel §R9). Log a one-line note
        # and swallow so the pipeline keeps running.
        try:
            (_HEALTH_DIR / "latest.md").write_text(
                f"[health-render] failed at "
                f"{dt.datetime.utcnow().isoformat(timespec='seconds')}Z: "
                f"{type(e).__name__}: {e}\n"
            )
        except Exception:
            pass


def _markdown(s: dict[str, Any]) -> str:
    """Owner-readable dashboard."""
    lines: list[str] = []
    started = s.get("started_at", "—")
    lines.append(f"# Briefing run — {started}")
    lines.append("")

    # Intake
    intake = s.get("intake") or {}
    if intake:
        n_in = intake.get("candidates_in", 0)
        n_accept = intake.get("accepted", 0)
        pct = (n_accept / n_in * 100) if n_in else 0
        lines.append("## Intake")
        lines.append(f"- candidates_in: {n_in}")
        lines.append(f"- accepted: {n_accept} ({pct:.1f} %)")
        lines.append(f"- rejected: {intake.get('rejected', 0)}")
        by = intake.get("reject_by_reason") or {}
        if by:
            lines.append("  - by-reason: " + ", ".join(
                f"{k}={v}" for k, v in sorted(by.items(), key=lambda kv: -kv[1])
            ))
        lines.append(f"- dedup_matches: {intake.get('dedup_matches', 0)}")
        lines.append("")

    # Content pipeline
    refine = s.get("refine") or {}
    if refine:
        lines.append("## Content pipeline")
        lines.append(f"- refine_stories: {refine.get('stories', 0)}"
                     f"  (avg latency {refine.get('avg_latency_s', 0)} s)")
        lines.append(
            f"- gemini_calls: {refine.get('gemini_calls', 0)}    "
            f"(est. ${refine.get('cost_estimate_usd', 0):.2f})"
        )
        lines.append("")

    # Audio
    audio = s.get("audio") or {}
    if audio:
        lines.append("## Audio")
        lines.append(f"- tts_generated: {audio.get('tts_generated', 0)}")
        lines.append("- whisper_wer:")
        lines.append(
            f"    p50={audio.get('wer_p50', 0):.3f}  "
            f"p90={audio.get('wer_p90', 0):.3f}  "
            f"p99={audio.get('wer_p99', 0):.3f}"
        )
        fail = audio.get("wer_fail_gate", 0)
        total = audio.get("tts_generated", 0) or 1
        lines.append(f"    fail_gate (>0.10): {fail}   ({fail/total*100:.1f} %)")
        per_voice = audio.get("per_voice") or {}
        if per_voice:
            lines.append("    voices:  " + "  ".join(
                f"{v}={w:.3f}" for v, w in sorted(per_voice.items())
            ))
        lines.append("")

    # Storage
    storage = s.get("storage") or {}
    if storage:
        lines.append("## Storage")
        lines.append(f"- s3_uploads_ok: {storage.get('s3_uploads_ok', 0)}")
        failed = storage.get('s3_uploads_failed', 0)
        marker = "" if failed == 0 else "  **⚠**"
        lines.append(f"- s3_uploads_failed: {failed}{marker}")
        lines.append("")

    # Run
    lines.append("## Run")
    lines.append(f"- start: {started}")
    lines.append(f"- end:   {s.get('ended_at', '—')}")
    dur = s.get('duration_s')
    if dur is not None:
        m, sec = divmod(int(dur), 60)
        lines.append(f"- duration: {m}m {sec}s")
    lines.append(f"- exit: {s.get('exit', 0)}")

    # Drift status
    drift = s.get("drift")
    if drift:
        from pipeline.drift import summarise_line
        status = drift.get("status", "?")
        marker = "  **⚠**" if status == "breach" else ""
        lines.append(f"- {summarise_line(drift)}{marker}")

    # Golden set status
    golden = s.get("golden")
    if golden:
        n = golden.get("n", 0)
        gate = "smoke" if n < 100 else "hard-fail"
        passed = "pass" if golden.get("pass") else "fail"
        lines.append(
            f"- golden_eval ({gate}): {passed} "
            f"(cat={golden.get('cat', 0)*100:.0f}%, "
            f"band={golden.get('band', 0)*100:.0f}%, "
            f"decision={golden.get('decision', 0)*100:.0f}%, "
            f"n={n})"
        )
    return "\n".join(lines) + "\n"
