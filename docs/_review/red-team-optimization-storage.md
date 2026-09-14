# Red-team review — design-review-optimization-storage.md

**Persona:** hostile skeptic. Not looking for what's right; looking for
what breaks. Assume the author was optimistic.

---

## R1. Merge A conflates temperature-sensitive stages

`distill` is a mechanical JSON extraction (temperature ~0.0). `draft`
is prose generation (temperature ~0.3). `stakes` is inference that
sometimes returns `"NONE"` (temperature ~0.2). **A single call can only
have one temperature.** The design hand-waves this. If you use 0.3 for
all three, `distill` becomes noisier and `key_facts` extraction quality
regresses — silently, because there's no per-stage unit test today.

**Fix required:** either (a) declare that `distill` runs at 0.3 and
demonstrate empirically that key-fact extraction doesn't regress, or
(b) keep `distill` as a separate call and only merge `draft + stakes`
(saves 1 call, not 2).

## R2. Merge B's self-check is a fox guarding the henhouse

`SelfCheck` is supposed to catch "audio_rewrite left digits in place"
or "audio_rewrite used an em-dash." But the model that made the mistake
is the same model asked to spot it. Empirically, LLMs asked to lint
their own output miss ~40% of the errors an external pass catches
(this is documented in every LLM-as-judge study). The design cites no
evidence that Kokoro's specific failure modes (unspaced acronyms,
digits) are within the model's own inspection blindspot.

**Fix required:** either (a) prove empirically that same-call
self-check catches ≥ 95% of what the standalone sanity call caught, or
(b) keep sanity separate. Merge B is the more speculative of the two.

## R3. §4.3 model upgrade budget assumes English-only cost model

Claude Haiku 4.5 at ~$1 in / $5 out per 1M tokens. Audio rewrites are
often 300–500 words = ~700–1200 tokens output. At 118 stories/run × 3
runs/day × 30 days = ~10,600 rewrites/mo × 1000 tokens avg = 10.6M
output tokens = **$53/mo**, not "+$3–5/mo" as claimed. Doc §4.3 is off
by an order of magnitude.

**Fix required:** recompute. If Haiku is $50+/mo it violates the
"< $10/mo total" implicit budget stated in §14.

## R4. §5.1 voice sweep is described as "reversible in one commit"; it isn't

Voices sound different across categories. A single owner listening
session picks one favourite per category — but different sample stories
would produce different picks. Once shipped, all new audio uses new
voices. **Old audio in the R2 bucket still uses the old voices.** After
sweep + R2 migration, the corpus contains a mix of voices for the same
category. UI cannot easily indicate this. Reversing means either
regenerating all audio (expensive) or accepting the inconsistency.

**Fix required:** either (a) call this out explicitly and accept the
mixed-voice period, (b) regenerate all audio after sweep (costs a full
TTS run, but Kokoro is free), or (c) delay §5.1 until §6 R2 lands so
the corpus is small when the sweep flips.

## R5. Punctuation preservation contradicts existing AUDIO_REWRITE prompt

The current audio rewrite prompt explicitly says "no dashes, parens,
semicolons — rephrase around them" (§15 of architecture overview).
§5.2 says restore em-dashes and colons. **These two rules will fight
each other every run.** The audio_rewrite strips them; normalize.py
puts them back in mechanically. Result: badly-placed punctuation that
neither the LLM nor a human wrote.

**Fix required:** update the AUDIO_REWRITE prompt to *allow* the specific
punctuation Kokoro rewards (`...`, `:`, `—`) while still forbidding
`;` and parentheticals. Or drop §5.2 entirely.

## R6. §6 R2 migration underestimates the `git filter-repo` step

The design says "one-way" but doesn't cover:

- All existing clones need to be re-cloned. Vercel's build cache may
  reference blob SHAs. Any GHA cache pointing at objects that no longer
  exist will break silently.
- Force-pushing to main can fight the cron push race the design
  proposes to fix with `git pull --rebase --autostash`. If a cron push
  happens between the rewrite and the force-push, the cron push wins
  and re-introduces the audio history.
- Any historical PR review URLs (github.com/.../commits/<sha>) break.
  Not critical for a single-user product but worth noting.

**Fix required:** RUNBOOK section for the purge that (a) puts the cron
in a maintenance-off state, (b) re-clones all working copies, (c)
verifies Vercel deploys correctly against the rewritten history, (d)
explicitly acknowledges the URL-breakage.

## R7. §7.1 drift detector will false-alarm on Phase 4 sourcefix commits

The design has a full source-list refresh planned (broken feed
replacements + adding Semafor, Rest of World, etc.). That will change
candidate volume by ~20%. Accept-rate is candidate-count-normalized so
it *shouldn't* shift, but adding 4 new outlets covering the same
stories will increase dedup hits — those come out of accepts.

If drift detection is P0 and runs on Phase 1 (before any source
changes), Phase 4 source changes will trigger the alarm and require
tuning the golden set. Order-of-operations problem.

**Fix required:** either (a) drift detection warmup extended to 14 days
across source list changes, (b) drift detection paused during known
disruptive changes, or (c) sourcefix work sequenced before drift
detection lands.

## R8. §7.2 golden set doesn't include time-anchor

Story-relevance drifts over calendar time. A "2026-09-04 fed rate cut"
story that was clearly-accept in September is stale by December. If the
golden set is time-anchored to `body_snippet` only, running the runner
in month 6 asks: is significance still 0.55–0.85 for this? Answer: no,
because the story is stale and significance should downrank staleness.

**Fix required:** either (a) golden set entries carry a `label_asof`
date and the runner treats stories as if published on that date, or
(b) golden set is periodically refreshed (which defeats the "hand-label
once" claim).

## R9. §7.3 health dashboard has no failure state for itself

If `pipeline/health.py` throws (division by zero on an empty run, JSON
serialization fail on some new field), the dashboard doesn't write and
the pipeline continues. Owner sees the last-successful dashboard and
thinks things are fine. **The dashboard failing is more likely than
the pipeline failing** because it's a thin new module.

**Fix required:** health render must be wrapped in try/except and on
failure write a "dashboard render failed at <ts>" line to
`data/health/latest.md`. Same rule for drift.py, golden runner, all
observability outputs.

## R10. §7.4 WER history is unbounded

`data/audio_wer_history.jsonl` appends forever. At ~118 stories × 3
runs × 30 days × 12 months = 127,440 rows/year. Not huge in bytes but
committed to git, on top of the very problem the design is trying to
solve (unbounded git growth).

**Fix required:** either (a) rotate: monthly files
`audio_wer_history_YYYY-MM.jsonl`, delete anything older than 6 months,
(b) move to R2 as an object, or (c) accept the growth and reason
about it explicitly (~5 MB/year is fine).

## R11. Cost model in §14 ignores R2 request charges

R2 charges Class A (writes) $4.50/million after 1M free/mo, Class B
(reads) $0.36/million after 10M free/mo. Design assumes 118 stories × 3
runs/day = ~10,600 writes/mo. Under 1M free. But **reads** at scale
matter. If a story is streamed at 128kbps × 3 min = 2.9 MB, and the
audio player fetches in chunks (Content-Range requests), a single play
could be 5–10 HEAD/GET requests. At 118 stories/day × 30 days ×
say 3 plays each = 10,620 plays × 8 requests = 85K requests/mo.
Well under free tier. **But if we ever expose the audio to a broader
audience (RSS embed, sharing), request counts scale.**

**Fix required:** cost model is fine for the single-user product;
document the request-tier ceiling explicitly and the trip-point at
which we'd need to reconsider.

## R12. §10 test plan does not test the R2 outage path

Design §13 mentions R2 outage → retry with backoff. But §10.4 load
tests only cover success. No integration test that simulates R2 5xx
and verifies the pipeline retries, falls through to local write, and
retries next cron.

**Fix required:** add `test_r2_outage_recovery` to §10.4.

## R13. §11 migration order puts observability before what it observes

Phase 1 lands drift + golden + WER history *before* any of the changes
they should be gating (Phase 2 LLM refactor, Phase 3 audio, Phase 4
R2). This means:

- Drift baseline is measured against the *current* pipeline, so Phase 2
  merges will look like a drift breach.
- Golden set is labelled against the *current* refine output, so any
  refine change looks like a golden regression.
- WER history baseline is against *current* voices, so voice sweep
  looks like a WER regression.

This is arguably right (observability first, then changes) but the
gates need to be relaxed for the transition period. **The design says
"soft failure for the first week" for the golden runner but not for
drift or WER weekly.**

**Fix required:** Phase 1 lands all observability in soft-fail mode.
Hard-fail flips per-tool after each subsequent phase's baseline is
established.

## R14. LLMProvider protocol lock-in

§4.2's Protocol signature `generate(prompt, *, schema, temperature,
max_tokens)` presumes prompt strings. But:

- Claude's best API is tool-use / structured output via
  `input_schema` and function definitions.
- Gemini's structured output is `response_schema`.
- OpenAI's is `response_format`.

Each has different capability + edge case handling. A single
`generate(prompt, schema=...)` signature papers over meaningful
differences (Claude's tool-use is more reliable than Gemini's
`response_schema` for complex nested types).

**Fix required:** admit the Protocol is best-effort; document which
provider gets tool-use vs response_schema; test schema-mode fallback
paths.

## R15. §5.3 IPA overrides depend on WER history that doesn't exist yet

§5.3 says "extract top-20 mispronunciations from WER history (§7.4)."
But WER history is populated by §7.4 which runs at Phase 1. Voice
overrides land in Phase 3 or later. So the ordering works. **But** the
top-20 list is empty at Phase 1 (no history) and only meaningful after
a week of WER data. §11 rollout doesn't call this out. Owner might
attempt §5.3 in Phase 3 with an incomplete list.

**Fix required:** Phase 6 IPA overrides gate on "at least 14 days of
WER history exists."

## R16. What if audio_rewrite upgrade actually regresses WER?

§13 mentions this risk but the mitigation is "revert." Reverting
means: keep the story with the regressed voice pattern? Regenerate it
with old model? The design isn't clear.

**Fix required:** the WER regression gate should trigger a
regeneration of the 1-day cohort before the flip, so no bad audio
persists in R2.

---

## Summary of things the design must address before external review

Ordered by severity:

1. **R3 (cost math off by 10×)** — hard fix; recompute Haiku spend.
2. **R2 (self-check blind-spot)** — hard fix; require evidence or split.
3. **R1 (Merge A temperature)** — hard fix; either split or prove.
4. **R5 (punctuation prompt conflict)** — hard fix; update prompt.
5. **R6 (git filter-repo gotchas)** — must have RUNBOOK before purge.
6. **R7 (drift alarm during sourcefix)** — sequencing / soft-fail.
7. **R13 (observability baseline)** — soft-fail all obs during transition.
8. **R14 (LLMProvider best-effort)** — document, don't fix now.
9. **R11 (R2 request-tier ceiling)** — document only.
10. **R4 (mixed-voice period)** — document trade-off.
11. **R8 (golden set time-anchor)** — add `label_asof` field.
12. **R9 (observability self-failure)** — add try/except in obs modules.
13. **R10 (WER history growth)** — monthly rotation.
14. **R12 (missing R2 outage test)** — add integration test.
15. **R15 (IPA gates on 14 days WER history)** — document.
16. **R16 (audio regression mitigation)** — regenerate cohort on revert.

Everything else, blue team can defend or ignore.
