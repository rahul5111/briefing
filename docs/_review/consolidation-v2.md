# Consolidation — External Panel Feedback Applied

**Date:** 2026-09-14
**Inputs:**
- `docs/_review/external-principal-sde.md`
- `docs/_review/external-solution-architect-ai.md`
- `docs/_review/red-team-optimization-storage.md`
- `docs/_review/blue-team-response.md`

**Output:** Design doc revised (in-place). Backlog updated to reflect
the reduced scope + strengthened evaluation layer. Any item not on
this list stays as written.

---

## 1. Both panels converged on these items — ACCEPTED IN FULL

| # | Item | Original position | New position |
|---|---|---|---|
| C1 | Audio-model upgrade (§4.3) as P0 | Ship 2.5 flash in Phase 5 | **Deferred to P2.** Runs only if §5.1–5.3 free wins fail to close the "robotic voice" complaint. Owner explicitly approves +$20/mo before this ships. |
| C2 | Golden set at n=30 as hard-fail gate (§7.2) | Hard-fail after 1 week soft | **Smoke test only at n=30.** No workflow exit code on failure. Hard-fail gate blocked until n≥100 exists AND per-category stratification is in place. |
| C3 | Drift `sys.exit(2)` on IQR breach (§7.1) | Fails workflow on breach | **Never fails workflow.** Value printed in health dashboard. Extend to distributional statistic (KS-test or binned histogram delta on score distribution) as P1 improvement. |
| C4 | Merge B split-then-A/B (§4.1 Phase 5b) | 5a ship, 5b evaluate | **5b deleted entirely.** Ship 5a (audio_rewrite via structured output for audio_text only). Keep sanity as separate call. Not worth $1/mo savings. |
| C5 | Missing dead-man's switch | Not addressed | **Add Healthchecks.io ping** in the cron. If workflow doesn't ping in 25h, Healthchecks emails owner. Free tier. 5 min setup. |

## 2. Principal SDE — unique items ACCEPTED

| # | Item | Change |
|---|---|---|
| P1 | §6.2 git-filter-repo purge unjustified for single-user product | **Delete the purge from Phase 4.** `.gitignore` in step 6 stops future growth; that's sufficient. Move purge to `docs/OPT-IN-OPERATIONS.md` as an owner-decision-required standalone procedure, gated behind an explicit "the 588 MB is causing observable pain" trigger. |
| P2 | LLMProvider Protocol shipping three untested provider stubs | **Ship Gemini-only.** No `ClaudeProvider` / `OpenAIProvider` classes. Interface stays open for future extension but doesn't pretend to abstract what it can't test. If model upgrade lands (§4.3, deferred to P2), it comes as a direct Claude client call, not through the Protocol. |
| P3 | Six new secrets with no rotation plan | **Add `docs/RUNBOOK.md` §Secrets** as prerequisite for R2 phase. Rotation cadence: R2 keys every 6 months, LLM keys every 12 months. Revocation procedure documented. This is 30 min of writing; done before Phase 4 lands. |
| P4 | No R2 upload integrity check | **Add post-upload HEAD + Content-Length verification.** If mismatch, retry once, then log to `data/audits/r2_upload_failures.jsonl` and fall through to the local-temp path. |
| P5 | Kokoro model-file hash pin (was P2, is a live SPOF) | **Promote to P0.** Two lines in CI to hash `.models/kokoro-*.onnx` against a checked-in expected hash. Fails workflow on mismatch. |
| P6 | Health dashboard as `data/health/latest.md` committed to git | **Git-ignore `data/health/`.** Regenerate every run into the working tree, but don't commit. Same rule for `data/drift/`. Not the anti-pattern this design is elsewhere fixing. |
| P7 | `data/reviews/` retention unaddressed | **Add rotation policy:** 30 days in-repo (unchanged), then archive to R2 under `reviews-archive/YYYY-MM/`. `data/reviews/` never grows beyond 30 days in git. |
| P8 | Response_schema "fallback via json.loads" is not a fallback | **Add a real fallback:** if `response_schema` returns something invalid, retry once at higher temperature (heuristic — sometimes T=0.0 produces cropped JSON that T=0.2 doesn't), then fall through to text-mode + regex-extract for the specific stage. Log to `data/audits/schema_failures.jsonl`. |

## 3. Solution Architect (AI) — unique items ACCEPTED

| # | Item | Change |
|---|---|---|
| A1 | Whisper `tiny.en` (~8-12% WER floor) can't arbitrate audio changes | **Upgrade to `distil-large-v3`** (faster than `medium.en`, similar accuracy, better VRAM profile) as prerequisite to any P0 audio change. Runs in the existing cron. Adds ~30s per validation run; acceptable. |
| A2 | Rule-based scorers for audio_rewrite required | **Add `pipeline/eval/audio_scorers.py`** with: numeric-preservation regex diff (extract all `\d[\d,.]*` from source and rewrite, expect containment or spelled-out equivalents), acronym letter-spacing coverage (compare acronyms in source to letter-spaced forms in rewrite), forbidden-punctuation counter (`;`, `(`, `)` must be zero), sentence-length distribution (12–20 word target, `p90 ≤ 25`). These gate the audio_rewrite change, not owner listening. |
| A3 | Model bake-off shortlist wrong; Sonnet 4.5 as ceiling | **Add Sonnet 4.5 to §4.3 bake-off** as ceiling reference. Compare all four (flash-lite, 2.5 flash, Haiku 4.5, Sonnet 4.5) against the rule-based scorers before any commitment. Sonnet not for production; it's the "how good could this be" reference. |
| A4 | Voice sweep n=1 rater × n=1 story per condition is not an eval | **Restructure §5.1 as MOS-Likert:** ≥ 3 stories per category × top-5 voices, 3-dim Likert (naturalness, clarity, category fit), ≥ 2 raters (owner + one friend, or blind-random shuffle so owner rates twice with a delay). Published to `data/eval/voice_sweep_YYYY-MM-DD.md`. Do not commit voice change on n=1. |
| A5 | Pearson ≥ 0.6 shadow-rollout threshold too loose | **Change to:** Spearman ≥ 0.85 AND Kendall's τ ≥ 0.7 AND per-decile agreement ≥ 80%. Pearson stays as an informational metric. |
| A6 | DRAFT batching lacks fuzz test | **Add fuzz test to §10:** inject malformed source in 1 of 8 stories × 100 batches. Verify per-story fallback recovers each failing story. Ship gate: 100% recovery. |
| A7 | LLM model version strings not logged | **Add `model_version` field** to every call's return in `pipeline/llm.py`. Persist to `data/reviews/*.txt` alongside prompt/response. Weekly diff of a fixed test-input set against baseline flags silent server-side model changes. |
| A8 | Ship prompt rewrites separately from structural merges | **Sequence change:** prompt rewrites (§4.4) ship in their own Phase 5.5, AFTER structural merges (Phase 2) and audio changes (Phase 3), with 7 days between. Regressions attribute correctly. |
| A9 | AUDIO_REWRITE lacks in-prompt example | **Add one worked example** to AUDIO_REWRITE prompt: `"$2.3B revenue" → "two point three billion dollars in revenue"`. Highest-ROI prompt change on the list. Ship in Phase 5.5. |
| A10 | DRAFT asks model to self-select length | **Pass length as parameter:** compute `target_words = clamp(source_words × 0.35, 150, 360)` deterministically. Prompt says "target {N} words ± 10%". Removes bimodal band-edge failure mode. |
| A11 | Characterisation tests for prompt-change surface (em-dash, colon, ellipsis) | **Add to §10** the characterisation test suite: run AUDIO_REWRITE on 20 fixture stories, snapshot punctuation distribution, fail the workflow if the distribution shifts unexpectedly after `normalize.py` changes land. |
| A12 | Kokoro determinism / chunking assumption unstated | **Document in §5.2:** ONNX inference is deterministic; chunk boundaries are not. WER comparisons are between different (source, normalizer-version) pairs, not against a fixed audio-byte baseline. |
| A13 | Significance rebuild lacks canary set | **Add canary set:** 20 hand-labelled stories with owner-desired rank order. Shadow-diff runner computes rank-agreement against canary in addition to global correlation. Failure blocks the flip. Store at `pipeline/eval/canary_significance.jsonl`. |
| A14 | IPA is Kokoro-specific vendor lock-in | **Documented trade-off, not fixed:** we accept the coupling because the entire audio stack is Kokoro-specific already. Note that if we ever move engines (Chatterbox, XTTS), the IPA overrides become a phonemizer/ARPAbet migration item. Added to §13 risks. |

## 4. Partial / documented trade-off

| # | Item | Position |
|---|---|---|
| T1 | Adopt `promptfoo` or `DeepEval` framework | **Evaluate but do not commit yet.** Add to backlog as a P2 spike: prototype the golden runner in `promptfoo` for one week; if setup is < 2h and output is at least as informative as the bespoke runner, migrate. Otherwise keep bespoke. |
| T2 | LLM-as-judge for content quality (Solution Architect §3) | **Add to backlog as P2** after n≥100 golden set exists. Use Sonnet 4.5 as judge (not Gemini judging Gemini) at ~$5–10/mo. Gate: only used to catch fact-drop on the AUDIO_REWRITE stage; never to arbitrate style. |
| T3 | Cost budget for eval explicitly | **Documented in revised §14:** eval LLM-as-judge budget ~$5–10/mo when it lands. Under our $30/mo ceiling. |
| T4 | Voice-routing produces mixed-corpus period (red-team R4) | **Documented in §5.1:** working-tree retention rotates the corpus in 14 days. Acceptable transition. Alternative — full regeneration on flip — remains an owner-decidable option but not the default. |

## 5. Rejected — none

Every item from both panels was accepted in full or in part with an
explicit trade-off. Zero rejections. This reflects the quality of both
reviews.

## 6. Sequence change — accepted from Principal SDE §5

**Old sequence:** Observability → LLM refactor → Audio → Storage → Model
upgrade → Batching/IPA.

**New sequence:**

1. **Storage first (was Phase 4).** R2 migration + `.gitignore` for MP3.
   Kokoro hash pin. Secret rotation runbook. No git-history purge.
2. **Whisper upgrade (new).** `tiny.en` → `distil-large-v3`. Prerequisite
   for meaningful audio evaluation.
3. **Audio quality (was Phase 3).** Structured voice sweep (MOS + ≥2
   raters), punctuation preservation (prompt-first, then normalizer),
   IPA overrides gated on 14 days of WER history.
4. **LLM refactor (was Phase 2).** Merge A only. `distill` stays
   separate. No LLMProvider abstraction — direct Gemini client with
   `model_version` logging.
5. **Observability spine (was Phase 1).** Health dashboard (git-ignored),
   WER history (monthly-rotated), drift as informational metric, golden
   set at n=30 as smoke test only.
6. **Prompt rewrites (new, isolated from structural changes).** AUDIO_REWRITE
   worked example, DRAFT deterministic length parameter. Alone in their
   own commit set.
7. **Golden set expansion (new).** Owner hand-labels to n≥100 with
   per-category stratification. This unlocks hard-fail gates.
8. **Reassess §4.3 model upgrade.** Only if §3 audio changes did not
   close the "robotic voice" complaint. Bake-off includes Sonnet 4.5.
9. **DRAFT batching + IPA overrides + significance rebuild.** All
   gated on prior phases.

## 7. Design doc revision summary

The design doc gets patched in place with:

- §4.1 rewritten: only Merge A ships. §4.3 (5b sanity merge) deleted.
- §4.2 rewritten: Gemini-only. No provider stubs.
- §4.3 rewritten: P2, gated on §5 outcomes, bake-off includes Sonnet.
- §5.1 rewritten: MOS-Likert methodology, ≥2 raters, ≥3 stories per
  category × top-5 voices.
- §5.3 rewritten: IPA lock-in trade-off documented.
- §6 rewritten: purge deleted, moved to opt-in operations. Integrity
  check added. Secret rotation prerequisite added.
- §7.1 rewritten: drift is informational-only; no `sys.exit(2)`.
- §7.2 rewritten: n=30 is smoke test; hard-fail after n≥100 + stratification.
- §7.4 unchanged (already accepted post red-team).
- §8.2 amended: `data/health/` git-ignored; `data/reviews/` rotates
  to R2 after 30 days.
- §10 amended: characterisation tests, fuzz test, rule-based audio
  scorers, distil-large-v3 upgrade.
- §11 rewritten with the new sequence.
- §13 risks: Kokoro model hash pin promoted; IPA lock-in noted.
- §14 cost model: LLM eval budget added; costs otherwise unchanged.
- §15 (new): Rule-based audio scorers.
- §16 (was §15) consistency review updated.

Plus a new `docs/RUNBOOK.md` and a new
`docs/OPT-IN-OPERATIONS.md` (git-history purge lives there).

**Post-consolidation scope:** ~40% smaller than the pre-review draft.
Free wins first. Paid upgrades gated. Evaluation strengthened before
it arbitrates real changes.
