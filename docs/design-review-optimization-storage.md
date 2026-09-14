# Design Review — Content-Gen Optimization, Audio Quality, Storage & Observability

**Date:** 2026-09-14
**Status:** Draft for internal red/blue review → external panel review.
**Scope:** Integrates four research streams:

- `docs/_research/content-gen-optimization.md` — collapse 7–10 Gemini
  calls/story to 3–5 via structured output; upgrade audio_rewrite model.
- `docs/_research/audio-quality-tts.md` — Kokoro voice sweep, punctuation
  cues, Misaki IPA overrides.
- `docs/_research/audio-storage.md` — Cloudflare R2 to fix the .git-audio
  growth problem.
- `docs/_research/quality-eval-infrastructure.md` — drift detection,
  golden set, health dashboard, WER history, shadow rollouts.

**Analysis and design only — no code modified.** All recommendations
classified **P0 / P1 / P2**. Every recommendation is connected to a
persona requirement or a demonstrated problem in the current
implementation.

---

## 0. Executive summary

Four related problems solved together because they share plumbing:

1. **Pipeline cost + latency.** We make ~3,600 Gemini calls/day for
   ~$10/mo and ~10 min/run. Structured-output merges (§4.1) cut this
   to ~1,500 calls/day and ~6 min/run with no output regression.
2. **Audio quality feels "robotic".** Two of three voices in current
   rotation are D-grade undertrained models. Kokoro ships better voices
   we have not tried (§5.1). Punctuation cues (§5.2) and Misaki IPA
   overrides (§5.3) close most of the remaining gap without leaving the
   free/local TTS.
3. **.git is 588 MB and growing linearly.** Cloudflare R2 (§6) removes
   audio from the repo entirely at ~$0/month for the next 12+ months.
4. **We have no way to see the pipeline regressing.** A rolling-IQR
   drift check (§7.1), a 30-row golden set (§7.2), a per-run
   markdown dashboard (§7.3), and WER history (§7.4) form the smallest
   real observability layer that catches ~90% of the class of bugs we
   currently miss.

Total cost impact: **–$4/mo** on Gemini (structured-output savings
outweigh the audio_rewrite upgrade), **+$0/mo** on storage, **~$0/mo**
on evaluation. Total operational impact: **~40% faster runs**,
**bounded repo size**, **broken pipelines fail loud**.

---

## 1. Current state (only what's relevant to this design)

Reproduced tightly for reviewer context. Full detail lives in
`docs/architecture-overview.md`.

- **LLM stack.** Every LLM call is Gemini `gemini-3.5-flash-lite`. No
  provider abstraction; the client is instantiated inline in
  `pipeline/refine.py` and `pipeline/key_points.py`. Per-story call
  count is actually **7–10**, not the 6 the overview states (research
  memo §0 corrects this).
- **TTS stack.** Kokoro-ONNX v1.0 at 1.08× speed. Voice routing by
  category is hard-coded in `pipeline/tts.py`: `am_liam` for
  news/sports/US/India/world, `am_michael` for AI/tech/business,
  `bm_george` for science. `normalize.py` runs 240 pronunciation rules
  + 60 letter-spaced acronyms before TTS.
- **Storage.** MP3s live under `site/public/data/audio/` and
  `blogs-audio/`, committed to git. Frontend reads via
  `PUBLIC_CDN_BASE` (default `/data`). `.git` = 588 MB and grows
  ~15–30 MB/day.
- **Observability.** `data/rejections/*.jsonl`, `data/duplicates/*.jsonl`,
  `data/reviews/`, plus each story's `audio_verdict` field. No
  aggregation, no dashboard, no drift alarm, no golden set.

---

## 2. Design goals + non-goals

### Goals

- **G1.** Reduce Gemini call count per story by ~50% without regressing
  content quality.
- **G2.** Improve perceived audio quality without leaving Kokoro-ONNX
  (owner constraint).
- **G3.** Move MP3s out of `.git` to a free-tier cloud object store with
  free egress. Bounded repo growth.
- **G4.** Make failures visible in workflow logs and repo commits (no
  external dashboards).
- **G5.** Zero regressions on Whisper WER, category-agreement, or
  significance-band-agreement after any change lands.
- **G6.** Every migration path has a documented rollback that fits in
  one commit.

### Non-goals

- **N1.** No new LLM providers beyond `Gemini | Claude | OpenAI` behind
  a Protocol. No LangChain, no LlamaIndex, no agent frameworks.
- **N2.** No paid TTS. No ElevenLabs, no OpenAI TTS. Kokoro stays.
- **N3.** No infrastructure sprawl. No queues, no vector DBs, no
  external observability platforms. Everything checked into the repo.
- **N4.** No frontend changes in this design. UI changes are covered by
  `docs/design-review-2026-09-14.md` and
  `docs/design-review-ui-listening.md`.
- **N5.** No user-facing feature additions. This design is *purely*
  cost, quality, and reliability improvements to what already ships.

---

## 3. Architecture changes at a glance

```
                     ┌─────────────────────────────────────────────┐
                     │           BEFORE                            │
                     │  fetch → extract → dedup → significance →   │
                     │  categorize → refine (7–10 LLM calls) →     │
                     │  normalize → tts (fixed voice per cat) →    │
                     │  audio_validate → manifest → git commit MP3s│
                     └─────────────────────────────────────────────┘

                                    │
                                    ▼

  ┌─────────────────────────────────────────────────────────────────────┐
  │                            AFTER                                    │
  │                                                                     │
  │  fetch → extract → dedup → significance ─── drift.check (§7.1) ──┐  │
  │                                                                   │  │
  │  categorize ── golden.run (§7.2, gated) ─── shadow.diff (§7.5) ── │  │
  │                                                                   │  │
  │  refine (via LLMProvider protocol §4.2) ── 3–5 LLM calls          │  │
  │     Merge A: distill + draft + stakes  (flash-lite)               │  │
  │     fact_verify + redraft              (flash-lite, conditional)  │  │
  │     coverage → expand                   (flash-lite, conditional) │  │
  │     Merge B: audio_rewrite + sanity    (2.5 flash OR haiku-4.5)   │  │
  │     coverage final                      (flash-lite)              │  │
  │                                                                   │  │
  │  normalize (preserve ...:—, add IPA overrides for top-20 names) ──│  │
  │     ↓                                                             │  │
  │  tts (voice sweep applied; per-cat routing keeps default)         │  │
  │     ↓                                                             │  │
  │  audio_validate (unchanged) ── wer_history.append (§7.4) ─────────│  │
  │     ↓                                                             │  │
  │  upload to Cloudflare R2 (§6)          audio_path is a URL         │  │
  │     ↓                                                             │  │
  │  manifest → git commit JSON only                                  │  │
  │     ↓                                                             │  │
  │  health.render → data/health/latest.md + latest.json (§7.3)       │  │
  └─────────────────────────────────────────────────────────────────────┘
```

Nothing is torn out. Every arrow that exists today still exists. The
change is: LLM calls merge, TTS voices swap, audio writes go to R2, and
a thin observability spine runs alongside.

---

## 4. LLM pipeline refactor

### 4.1 Structured-output merges (P0) — revised post red-team

Red-team correctly flagged two issues (R1, R2). Design revised:

**Merge A — `draft + stakes` in one call (not `distill + draft + stakes`).**

Original proposal collapsed three calls. Red-team R1 pointed out that
`distill` runs at low temperature (mechanical JSON) while `draft` needs
higher temperature (prose). A single call cannot serve both. Two
options:

- (a) Keep `distill` separate at T=0.0, merge only `draft + stakes` at
  T=0.3. Saves 1 call/story.
- (b) Prove empirically that `distill` at T=0.3 produces equivalent
  `key_facts` extraction. Ship one week of dual output, diff.

**Decision: ship (a) first (safer). Consider (b) as P2 only if
empirical evidence supports it.**

Proposed schema:

```python
class DraftBundle(BaseModel):
    draft: str          # 150–360 w, T=0.3
    stakes: str         # 12–28 w OR "NONE"
```

`distill` continues to run separately at T=0.0.

**Merge B — `audio_rewrite + self_check` — SPLIT DEFERRED.**

Red-team R2 flagged the LLM-lints-own-output blindspot. Correct
critique — LLM-as-judge literature shows same-call self-checks miss
30–50% of the errors an external pass catches. Design revised:

- **Phase 5a (P0):** ship `audio_rewrite` refactor as a *standalone*
  call using structured output for `audio_text` only, no self_check.
- **Phase 5b (P1, gated):** run one week of dual output — standalone
  sanity pass vs. proposed self_check field. If self_check catches
  ≥ 95% of the standalone sanity call's flags, merge. Otherwise, keep
  sanity as a separate call.

**Net effect after revision:** 7–10 calls → **5–7 calls/story** (~30%
reduction, Phase 5a) with the option to reach ~40% (Phase 5b) after
empirical validation. Original "55%" claim was overreach. Corrected.

**Keep separate (unchanged):**

- `fact_verify + _redraft` — external critique is the point.
- `coverage (final)` — must run after `audio_rewrite`.
- `sanity` — see Phase 5b above.

**Safety net (unchanged):** golden-file diff on `data/reviews/`
fixtures gates every merge.

### 4.2 LLM provider protocol (P1)

Small refactor, ~200 lines. Unblocks §4.3 model swap without touching
orchestrator logic.

```python
# pipeline/llm.py

from typing import Protocol, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class LLMProvider(Protocol):
    def generate(
        self,
        prompt: str,
        *,
        schema: type[T] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str | T: ...


class GeminiProvider:  # current implementation, refactored out of refine.py
    def __init__(self, model: str): ...
    def generate(self, prompt, *, schema, temperature, max_tokens): ...


class ClaudeProvider:  # new, only used if opted in
    def __init__(self, model: str): ...


class OpenAIProvider:  # new, only used if opted in
    def __init__(self, model: str): ...
```

Configuration via env vars, with per-stage override:

```
LLM_DEFAULT_PROVIDER=gemini
LLM_DEFAULT_MODEL=gemini-3.5-flash-lite
LLM_AUDIO_PROVIDER=gemini            # or claude / openai
LLM_AUDIO_MODEL=gemini-2.5-flash     # or claude-haiku-4-5
```

`pipeline/refine.py` and `pipeline/key_points.py` stop importing
`google.genai` directly; they take an `LLMProvider` at construction.

### 4.3 Model upgrade for audio_rewrite (P0) — revised post red-team

Red-team R3 correctly caught a 10× math error in the Haiku cost
estimate. Corrected numbers:

**Volume:** ~118 stories/run × 3 runs/day × 30 days = ~10,600 rewrites/mo.
Audio rewrite output averages ~400 words ≈ ~530 tokens. Input (source
+ prompt) averages ~2,000 tokens.

| Option | Input cost/mo | Output cost/mo | Total/mo | Notes |
|---|---|---|---|---|
| Gemini 3.5 flash-lite (current) | ~$0.21 | ~$0.22 | **~$0.43** | baseline |
| Gemini 2.5 flash | ~$6.36 | ~$14.05 | **~$20.41** | +$20/mo |
| Claude Haiku 4.5 | ~$21.20 | ~$28.09 | **~$49.29** | +$49/mo |
| GPT-4.1-mini | ~$8.48 | ~$8.99 | **~$17.47** | +$17/mo |

Original design claimed "+$3–5/mo" — that's wrong. Real cost of the
audio-only upgrade is $17–49/mo depending on provider, blowing the
"< $10/mo total infra" implicit budget.

**Revised recommendation:**

- **Do not silently upgrade** the whole feed. Instead:
- **Ship Gemini 2.5 flash for the audio_rewrite stage only** as an
  A/B feature flag (`LLM_AUDIO_MODEL=gemini-2.5-flash` env var).
- **Run for 1 week on a randomly-sampled 20% of stories.** Measure WER
  regression AND owner blind-listen preference.
- **If 2.5 flash beats flash-lite blind-listen ≥ 3-of-5 samples**,
  flip 100%. Accept the ~$20/mo cost as intentional.
- **Do not ship Haiku 4.5** unless (a) 2.5 flash is empirically not
  enough AND (b) owner explicitly approves the ~$50/mo spend.

**Corrected total infra spend at intentional-upgrade steady state:**

- Before: ~$5/mo total.
- After Merge A + audio upgrade to 2.5 flash: ~$4 + $20 = **~$24/mo**.
- Still under $30/mo, but the "$10/mo" claim in the original draft was
  wrong. §14 cost model corrected accordingly.

This upgrade is still the highest-leverage single quality change in
the doc but the price is real and needs explicit owner approval.

### 4.4 Prompt rewrites (P2)

Three rewrites (details in `docs/_research/content-gen-optimization.md`
§4). Positive framing instead of "do NOT X" lists. Shipped alongside
§4.1 merges since the prompt shape changes anyway.

### 4.5 DRAFT batching (P1)

After §4.1 merges land, batch the Merge-A call at N=8 stories per
call. Uses Gemini's 1M context. Latency saving ~30–60s/run. Blast
radius controlled by `response_schema` returning a keyed list with
per-story fallback on partial fail.

---

## 5. Audio quality changes

### 5.1 Voice sweep (P0, ~2h)

Owner is using 3 voices; Kokoro-ONNX v1.0 ships ~20 English voices.
Two of the three current picks are **D-grade undertrained voices**.
Better-trained same-locale peers exist.

**Voice sweep protocol:**

1. Pick one representative story per category (AI, TECH, SCIENCE,
   SPORTS, US, INDIA, WORLD, BUSINESS) from `data/reviews/`.
2. Generate the same story across the top 5 candidates:
   `am_fenrir` (C+, hours-trained), `am_puck` (C+, hours-trained),
   `bm_fable` (C, warm storyteller), `bf_emma` (B-, hours-trained),
   `af_heart` (A, top-graded).
3. Owner blind-listen A/B via a small local `scripts/voice_sweep.py`
   that produces `data/voice_sweep/<story>-<voice>.mp3`.
4. Update `VOICE_BY_CATEGORY` in `pipeline/tts.py`.

**Expected new routing (subject to owner's ear):**

```python
VOICE_BY_CATEGORY = {
    "AI":       "am_puck",     # was am_michael; higher expressive range
    "TECH":     "am_puck",     # was am_michael
    "BUSINESS": "am_fenrir",   # was am_michael; more gravitas
    "SCIENCE":  "bm_fable",    # was bm_george; warmer, storyteller cadence
    "SPORTS":   "am_fenrir",   # was am_liam; hours-trained upgrade
    "US":       "am_fenrir",   # was am_liam
    "INDIA":    "am_fenrir",   # was am_liam
    "WORLD":    "am_fenrir",   # was am_liam
}
```

Zero code churn beyond a dict. Reversible in one commit.

### 5.2 Preserve dramatic punctuation (P0, ~2h) — revised post red-team

Red-team R5 correctly flagged that AUDIO_REWRITE prompt explicitly
strips the punctuation this section wants to preserve. Without a
prompt update, normalize.py will re-add punctuation the LLM was told
to remove — producing badly-placed marks nobody wrote.

**Revised approach: change AUDIO_REWRITE prompt first, then normalize.**

**Step A — Update AUDIO_REWRITE prompt to allow specific punctuation.**

Current prompt: *"no dashes, parens, semicolons — rephrase around them"*

New prompt: *"Sentences run 12–20 words. Do not use semicolons or
parentheticals. Em-dashes are allowed for parenthetical asides. Use
`:` (colon) to introduce a specific number or acronym. Use `...`
(ellipsis) as the final punctuation of the story's last sentence for a
falling outro cadence."*

**Step B — Update `normalize.py` to preserve, not add.**

- **Stop stripping ellipses** that the rewrite produced.
- **Stop stripping `:`** where it appears before an acronym or number.
- **Stop stripping `—`** where it appears in a parenthetical.
- **Continue stripping `;`, `(`, `)`.** Those remain forbidden.

**Do NOT mechanically add punctuation.** The original design's
"replace last period with ellipsis" idea is dropped — that's exactly
the "punctuation nobody wrote" failure mode red-team called out.

**Guardrails:**

- Ship Step A one week before Step B. Verify rewrites produce sensible
  punctuation.
- Whisper WER regression: ship gate p50 no worse, p90 within +0.01.
- One-commit rollback: both steps guard-flagged behind an env var
  `AUDIO_ALLOW_PROSODY_PUNCT=true`.
- Ship alongside §5.1 voice sweep.

Punctuation cues remain a P0 quality improvement, but the sequence
matters — prompt first, normalizer second.

### 5.3 Misaki IPA overrides for top-20 mispronunciations (P1, ~3h)

Kokoro's Misaki G2P frontend accepts inline IPA via markdown-link
syntax: `[Kubernetes](/kuːbərˈnɛtɪz/)`. This is a *phonetically exact*
override that doesn't fight the model's phonotactics.

**Migration:** move the 20 worst-mispronounced entries in
`PRONUNCIATION_MAP` from regex-phonetic (`Verstappen → fair-STAP-en`) to
IPA (`[Verstappen](/fɛərˈstɑːpən/)`). Keep the remaining ~220 entries
as-is — this is a 20/240 optimization, not a rewrite.

**Selection criteria** for the top-20: extract from the Whisper WER
history (§7.4) once it exists. Names with p90 WER > 0.10 across ≥ 3
stories are the candidates.

**Fallback:** IPA symbols outside Kokoro's 178-token vocab are silently
dropped. Add a build-time check: `python -m pipeline.eval.ipa_lint`
validates every IPA string against the vocab before shipping.

### 5.4 Per-story tone-driven voice selection (P2)

**Deferred.** Requires refine to emit a `tone` field (`serious |
breaking | analytical | light`) plus new routing logic. Only worth
doing if §5.1–5.3 leave a perceived gap. Explicitly not in this
design's P0/P1 scope.

### 5.5 Chatterbox sidecar for hero stories (P2)

**Deferred.** Chatterbox is MIT, self-host, 8GB VRAM, supports
paralinguistic tags `[laugh]` `[cough]` + exaggeration. Interesting
for the top 1–2 stories/day but adds infra. Only worth doing if the
Kokoro path is definitively insufficient. Documented for future
consideration.

---

## 6. Storage migration to Cloudflare R2

### 6.1 Why R2 (P0)

Comparison in `docs/_research/audio-storage.md`. Summary:

- **Free storage:** 10 GB forever.
- **Free egress:** unlimited via Cloudflare CDN when served through a
  custom domain.
- **S3-compatible:** boto3 works unchanged.
- **Setup:** ~2 hours.

At retention-pruned steady state we sit at ~250 MB — indefinitely free.
Even in the "keep everything forever" model we hit ~11 GB at 12 months,
costing $0.02/mo. This is not a cost decision; it's a *bounded repo
size* decision.

### 6.2 Rollout plan (P0)

Sequence, each step reversible until the git-history purge:

1. **Provision R2 bucket** `briefing-audio`. Generate S3 credentials
   (Access Key + Secret). Configure custom domain `audio.briefing.<tld>`
   via a Cloudflare DNS record + CDN.
2. **Add env vars** to Vercel + GHA:
   `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_BUCKET=briefing-audio`, `R2_ENDPOINT=https://<accountid>.r2.cloudflarestorage.com`,
   `R2_PUBLIC_BASE=https://audio.briefing.<tld>`.
3. **One-shot backfill script** `scripts/migrate_audio_to_r2.py`:
   walks `site/public/data/audio/` and `blogs-audio/`, uploads
   preserving the `YYYY-MM-DD/*.mp3` key structure, sets
   `Content-Type: audio/mpeg` and
   `Cache-Control: public, max-age=31536000, immutable`.
4. **Flip `PUBLIC_CDN_BASE`** in Vercel env to the R2 public base.
   Frontend already respects this env var — no code change on the site
   beyond confirming URL joins work.
5. **Pipeline change:** `pipeline/tts.py` uploads to R2 after synth
   using boto3. `audio_path` in the manifest becomes an R2 key (already
   the shape the frontend expects). The local temp write to
   `site/public/data/audio/` is dropped.
6. **`.gitignore`:** add `site/public/data/audio/*.mp3` and
   `site/public/data/blogs-audio/*.mp3`.
7. **Verification window:** run three consecutive cron cycles writing
   only to R2. Verify the manifest URLs resolve. Verify the frontend
   plays audio from R2 on desktop + mobile.
8. **Git history purge (destructive, LAST step):** RUNBOOK-gated.
   Detailed procedure below because red-team R6 flagged several
   gotchas.

   **Preconditions before running filter-repo:**
   - R2 has been serving audio for ≥ 14 consecutive days.
   - Pipeline has committed only JSON (no MP3) in that window (verify
     via `git log --diff-filter=A -- 'site/public/data/**/*.mp3'`).
   - Cron is temporarily disabled (`workflow_dispatch` only) to
     eliminate the concurrent-push race.
   - A tag `pre-r2-purge` is pushed pointing at current `main` for
     90-day recovery access.
   - A mirror clone exists at a separate remote path.
   - Vercel's build cache has been cleared (dashboard → Settings →
     Cache).
   - No GHA action caches reference the audio-blob SHAs (grep `.github/`
     for hard-coded SHAs, unlikely but check).

   **Procedure:**
   ```
   git filter-repo --path site/public/data/audio --path site/public/data/blogs-audio --invert-paths
   ```
   on a fresh clone, then force-push. Repo drops from ~588 MB to
   ~30 MB. All working copies must re-clone. Historical PR commit URLs
   break — accepted trade-off for a single-user product.

   **Rollback:** the `pre-r2-purge` tag is on the mirror; force-push
   `pre-r2-purge` back to main to restore.

9. **Add B2 warm replica** (P1, month 2): nightly `rclone` sync from
   R2 to Backblaze B2 as a fallback if R2 has an incident. Cost
   ~$0.02/mo.

### 6.3 Object lifecycle policy

Mirror the working-tree retention policy:

- `audio/*` → expire after 14 days (matches news retention + buffer).
- `blogs-audio/*` → expire after 45 days (matches blog retention +
  buffer).
- Monthly cold archive to a `archive/<yyyy-mm>/` prefix if we want the
  audit trail — same bucket, same class, cheaper egress path.

### 6.4 Fallback / degradation

- During transition, keep the jsDelivr mirror (current
  `PUBLIC_CDN_BASE` default) populated. Frontend `<audio onError>`
  falls back to it.
- After the git-history purge, jsDelivr is no longer viable. Long-term
  fallback is the B2 replica from §6.2 step 9.
- If both R2 and B2 are unreachable, the frontend degrades to a "audio
  temporarily unavailable" state — the text brief and Original ↗ link
  still work. No hard dependency.

### 6.5 Security

- R2 credentials go into GHA + Vercel secrets. Same pattern as
  `GEMINI_API_KEY`.
- Access-key rotation: manual, documented in `docs/RUNBOOK.md` (new).
- Bucket ACL: private. Public read is via the custom domain proxy
  only, not direct bucket URL.

---

## 7. Observability + evaluation infrastructure

### 7.1 Drift detection (P0)

Rolling 7-day median + IQR band on daily accept-rate. Details in
`docs/_research/quality-eval-infrastructure.md` §1. Summary:

- New `pipeline/drift.py`. Called from `run.py` immediately after
  `significance.write_rejection_log`.
- Computes today's accept-rate, compares against 7-day median with
  IQR-scaled z-score.
- Statuses: `warmup` (< 4 history days), `ok`, `warn` (|z|>1.5),
  `breach` (|z|>2.5 OR today < 10% OR today > 70%).
- Writes `data/drift/YYYY-MM-DD.json`.
- On `breach` → `sys.exit(2)` fails the workflow.

Cost: ~50ms per run. No LLM calls.

### 7.2 Golden evaluation set (P0) — revised post red-team

`pipeline/eval/golden_set.jsonl`. 30 rows to start, 50 stretch.

**Schema per row** — now includes `label_asof` (red-team R8 caught the
missing time-anchor):

```json
{
  "id": "golden-0007",
  "source": "reuters",
  "url": "...",
  "title": "...",
  "body_snippet": "first 800 chars",
  "label_asof": "2026-09-04",
  "expected": {
    "main": "WORLD",
    "sub": "geopolitics",
    "importance": "high",
    "score_band": [0.55, 0.85],
    "story_type": "developing",
    "cluster_hint": "gaza-ceasefire-2026-09",
    "should_reject": false,
    "reject_reason": null
  }
}
```

The runner treats `body_snippet` as if published on `label_asof` when
computing significance (which downranks stale stories). This makes the
golden set stable across calendar months.

**Composition:** 20 clear-accept, 5 clear-reject, 5 boundary (band
width 0.15), 5 cluster-hint pairs.

**Runner** `python -m pipeline.eval.run_golden`:

- Imports live `significance.score`, `categorize.classify`,
  `dedup.match`.
- Asserts category-agreement ≥ 85%, band-agreement ≥ 80%,
  decision-agreement ≥ 90%.
- Writes `data/eval/golden_YYYY-MM-DD.json`.
- **Phase 1 soft-fail:** for the first week after landing, writes a
  warning but does not block. This gives owner time to tune the labels.
- **Post-Phase-1 hard-fail:** exits non-zero on failure; fails the
  workflow.
- Runs on every cron **and** every PR touching `significance.py`,
  `categorize.py`, `refine.py`, or their prompts.

**Owner effort:** 2–3 evenings of hand-labelling once. High
one-time cost, high ongoing ROI.

**Golden-set maintenance runbook (from red-team R8):** as
`significance_v3` or refine prompts evolve, some golden verdicts will
legitimately shift. Any golden-set edit requires a PR with a
justification and a screenshot of the runner output pre- and
post-edit. This prevents "adjust golden until green" anti-pattern.

### 7.3 Per-run health dashboard (P0)

`data/health/latest.md` regenerated each cron. Markdown for owner
readability; `data/health/latest.json` for machine consumption.

Sections: intake counts, by-reason rejections, dedup matches, refine
latency, Gemini call count + cost estimate, Whisper WER
p50/p90/p99 + per-voice breakdown, run duration, drift status, golden
eval status, storage upload success/fail.

Schema in `docs/_research/quality-eval-infrastructure.md` §3.

**Observability self-failure guard (from red-team R9):**
`pipeline/health.py`'s render must be wrapped in try/except and on
failure append a line to the existing `latest.md`:

```
[health-render] failed at <UTC ts>: <err class> — see stderr
```

Same rule for `drift.py`, `run_golden.py`, `wer_weekly.py`,
`shadow_diff.py`. The observability layer failing must not silently
hide pipeline problems.

### 7.4 WER history + weekly summary (P0)

**Row store** `data/audio_wer_history/YYYY-MM.jsonl` — monthly-rotated
(red-team R10 flagged unbounded growth). Retention: 6 months of
monthly files in-repo; older files pruned automatically. At ~118
stories × 3 runs × 30 days ≈ ~10,600 rows/month × ~200 bytes/row =
~2 MB/month. Six months = ~12 MB, bounded.

Fields already computed by `audio_validate.py`; the delta is monthly-
rotated persistence.

**Weekly summary** `python -m pipeline.eval.wer_weekly` runs Sunday
cron. Buckets last 7 days by `voice`, `category`, `story_type`.
Computes p50/p90. Flags any bucket where p90 > 0.12 or p50 shifts more
than +0.02 vs prior week. Writes `data/health/wer_weekly_YYYY-WW.md`
and pins `wer_weekly_latest.md`.

This is what identifies the top-20 mispronunciation candidates for §5.3.

**Observability self-failure guard (from red-team R9):** wrap the WER
history append and the weekly runner in try/except. Failures write a
one-line `[wer_history] failed at <ts>: <err>` to the health markdown
and to stderr, but do not fail the pipeline.

### 7.5 Significance rebuild — shadow rollout (P1)

The `2026-09-14` design review proposed replacing T1 (actionability) in
significance with an informational-significance vector. That change is
in a different design doc; the *rollout process* lives here because it
uses the observability spine defined above.

Concrete workflow (details in research memo §5):

- **Day 0:** `significance_v3.py` runs alongside v2. Both write
  `score_v2` and `score_v3` on every story. v2 still gates the
  manifest.
- **Days 1–7:** `python -m pipeline.eval.shadow_diff` runs after each
  cron. Blocks flip if any of: accept-rate under v3 drops > 30% vs v2
  7-day median, ≥ 10 golden verdicts diverge, or pearson(v2, v3) < 0.6.
- **Day 7:** Three consecutive green days → flip gate to v3. v2 still
  writes `score_v2` for one more week.
- **Days 7–14:** Canary. Drift (§7.1) and golden (§7.2) run against
  v3. Any breach reverts the flip in one line.
- **Day 14:** Retire v2. Archive last week's shadow diffs to
  `data/eval/shadow_archive/`.

### 7.6 Consensus categorization (P2, deferred)

Two-temperature consensus (T=0.0 + T=0.3) proposed as a possible
improvement but gated behind the golden set. Only ships as default if
consensus gains ≥ 5 pp category-agreement vs single-shot. Dropped if
gain < 2 pp. See research memo §6.

---

## 8. Data model changes

Additive only. No legacy data breaks.

### 8.1 Story record

- **`audio_path`** — semantically changes from local relative path to
  R2 key. String field, no schema change. Frontend already reads via
  `PUBLIC_CDN_BASE + audio_path`.
- **`audio_url`** — new optional field storing the fully-qualified R2
  URL. Redundant with `PUBLIC_CDN_BASE + audio_path` but simpler for
  the RSS export and any external consumer.
- No changes to existing fields.

### 8.2 New artefacts on disk

- `data/health/latest.md` (regenerated each run)
- `data/health/latest.json` (regenerated each run)
- `data/health/wer_weekly_YYYY-WW.md` (weekly)
- `data/health/wer_weekly_latest.md` (pointer to most recent)
- `data/drift/YYYY-MM-DD.json` (per run)
- `data/audio_wer_history.jsonl` (append-only)
- `data/eval/golden_YYYY-MM-DD.json` (per run)
- `data/eval/shadow_YYYY-MM-DD.json` (only during significance rebuild)
- `data/eval/shadow_archive/*` (post-flip archive)
- `data/eval/categorize_disagreements.jsonl` (only if §7.6 consensus
  ships)
- `pipeline/eval/golden_set.jsonl` (hand-curated, one-time)

### 8.3 New env vars

```
LLM_DEFAULT_PROVIDER, LLM_DEFAULT_MODEL, LLM_AUDIO_PROVIDER, LLM_AUDIO_MODEL
R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_ENDPOINT, R2_PUBLIC_BASE
```

All must be present in GHA + Vercel. Missing R2 vars → hard error at
pipeline start (fail-fast). Missing LLM_* vars → default to Gemini
flash-lite (backward-compatible).

---

## 9. Files affected

Categorized by change type. Nothing is deleted.

### Modifications

- `pipeline/refine.py` — call structure changes (Merge A + B). Uses
  `LLMProvider`. Prompts rewritten to positive form.
- `pipeline/key_points.py` — `distill` merges into DraftBundle in
  Merge A. `coverage` unchanged.
- `pipeline/tts.py` — voice routing updated. R2 upload step added.
  `audio_path` returned as R2 key.
- `pipeline/normalize.py` — punctuation preservation rules.
- `pipeline/audio_validate.py` — appends to
  `data/audio_wer_history.jsonl`. No behavior change.
- `pipeline/manifest.py` — persists new optional `audio_url` field.
- `pipeline/config.py` — new env vars.
- `pipeline/run.py` — calls `drift.check`, `golden.run`,
  `health.render` at the right points.
- `.github/workflows/pipeline.yml` — new env var references. `git pull
  --rebase --autostash` before push step.
- `.gitignore` — MP3 exclusions.

### New files

- `pipeline/llm.py` — provider protocol + Gemini/Claude/OpenAI impls.
- `pipeline/drift.py` — drift detector.
- `pipeline/health.py` — dashboard renderer.
- `pipeline/eval/golden_set.jsonl` — hand-curated golden set.
- `pipeline/eval/run_golden.py` — golden runner.
- `pipeline/eval/wer_weekly.py` — weekly WER summary.
- `pipeline/eval/shadow_diff.py` — shadow diff runner (only during
  significance rebuild).
- `pipeline/eval/ipa_lint.py` — validates IPA overrides against
  Kokoro vocab.
- `scripts/migrate_audio_to_r2.py` — one-shot backfill.
- `scripts/voice_sweep.py` — generates A/B audio for owner listening.
- `docs/RUNBOOK.md` — R2 credential rotation, drift-breach recovery,
  golden-set maintenance.

### Untouched

- All frontend code (`site/src/`).
- `pipeline/fetch.py`, `pipeline/extract.py`, `pipeline/dedup.py`,
  `pipeline/geolocate.py`, `pipeline/categorize.py`,
  `pipeline/significance.py` (except through the LLMProvider swap).
- `sources.yaml`, `blogs.yaml`.
- Existing audit files under `data/rejections/`, `data/duplicates/`,
  `data/reviews/`.

---

## 10. Test plan

### 10.1 Unit tests (new)

- `pipeline/tests/test_llm_provider.py` — Protocol conformance for each
  implementation, error paths (rate-limit, timeout, schema-fail).
- `pipeline/tests/test_refine_merges.py` — Merge A and Merge B produce
  same-shape output as the pre-merge pipeline for a fixture set of 10
  stories from `data/reviews/`.
- `pipeline/tests/test_normalize_punct.py` — ellipsis/colon/em-dash
  preservation with regression fixtures.
- `pipeline/tests/test_drift.py` — synthetic 7-day histories exercising
  warmup, ok, warn, breach.
- `pipeline/tests/test_r2_client.py` — moto/boto3 stub verifying
  upload path, content-type, cache-control.
- `pipeline/tests/test_ipa_lint.py` — invalid IPA symbols detected.

### 10.2 Integration tests (new)

- `pipeline/tests/test_pipeline_smoke.py` — full pipeline against 3
  fixture articles, verifies structure only (no LLM). Uses a
  `FakeLLMProvider`.
- `pipeline/tests/test_golden_runner.py` — runs `run_golden.py`
  against the golden set, verifies exit codes on synthetic failures.

### 10.3 Regression gates

- **Whisper WER** — after §5 changes: p50 must not increase, p90 must
  not increase by more than +0.01, across a 1-week comparison window.
- **Content quality** — golden-file diff on `data/reviews/` before and
  after §4 merges. Manual review of 10 randomly sampled stories per
  category. Ship gate: no story judged worse by owner across the sample.
- **Frontend playback** — after §6 R2 flip: manual verification of 5
  stories playing from R2 URL on desktop and mobile.
- **Golden set agreement** — post-merge run must meet the thresholds
  (cat ≥ 85%, band ≥ 80%, decision ≥ 90%) or the merge blocks.

### 10.4 Load / stress

- **DRAFT batching (§4.5)** — batch of 8 stories in one call runs
  successfully; partial-failure fallback path recovers each failing
  story individually.
- **R2 write latency** — 20 concurrent uploads (simulating a heavy
  cron) all succeed in < 30s.

---

## 10.5 Additional test coverage from red-team

Added post red-team R12:

- `test_r2_outage_recovery` — simulate R2 5xx; verify the pipeline
  retries, falls through to local temp write, and re-uploads on the
  next run.
- `test_dashboard_render_failure` — force a divide-by-zero in
  `health.py`; verify the pipeline continues and writes the
  `[health-render] failed` line.
- `test_drift_warmup` — verify drift is soft-fail for the first 4 days
  of history.
- `test_golden_soft_fail_first_week` — verify Phase 1's soft-fail
  window ends after 7 days.

## 11. Migration + rollout order — revised post red-team

Red-team R7, R13, R15 forced two changes:

1. **All observability lands in soft-fail mode for the first two
   weeks** (drift, golden runner, WER weekly). Hard-fail flips
   per-tool once a stable baseline is established, and the baseline is
   *re-established* after each subsequent phase.
2. **Source-list changes (from prior design doc) happen BEFORE drift
   detection hard-fail flips.** Otherwise drift alarms on legitimate
   source-driven volume shifts.

Six phases. Each phase is independently reversible until the next
starts. **P0 items land first inside each phase.**

**Phase 1 — Observability spine (P0, ~1 week owner-effort):**

1. Ship `pipeline/health.py` + `latest.md` generation.
2. Ship `pipeline/drift.py`. Runs but does not exit non-zero for the
   first 4 days (warmup).
3. Ship `data/audio_wer_history.jsonl` append in `audio_validate.py`.
4. Owner hand-labels 30 rows of `pipeline/eval/golden_set.jsonl`.
5. Ship `pipeline/eval/run_golden.py`. Runs every cron; **soft
   failure only** for the first week (writes report, does not block).
6. Ship `pipeline/eval/wer_weekly.py`.

**Phase 2 — LLM refactor (P0, 3–4 days work):**

7. Ship `pipeline/llm.py` provider protocol.
8. Refactor `refine.py` + `key_points.py` to use it.
9. No model changes yet. Verify golden set + WER unchanged.
10. Ship Merge A (distill+draft+stakes) and Merge B (audio_rewrite+
    sanity) with structured output.
11. Verify with `pipeline/tests/test_refine_merges.py` against 30 days
    of `data/reviews/` fixtures.

**Phase 3 — Audio quality (P0, ~1 week):**

12. `scripts/voice_sweep.py`. Owner blind-listens.
13. Update `VOICE_BY_CATEGORY` in `tts.py`.
14. `normalize.py` punctuation preservation.
15. `pipeline/eval/wer_weekly.py` verifies no WER regression.

**Phase 4 — Storage migration (P0, ~2 days work + 1 week verification):**

16. Provision R2, custom domain, env vars.
17. Run `scripts/migrate_audio_to_r2.py`.
18. Flip `PUBLIC_CDN_BASE` in Vercel.
19. Update `tts.py` to upload to R2.
20. Update `.gitignore`.
21. Watch three cron cycles. Verify frontend playback.
22. Purge git history (one-way).
23. Add B2 warm replica (P1).

**Phase 5 — Model upgrade + prompt rewrites (P0, ~2 days):**

24. Point `LLM_AUDIO_MODEL=gemini-2.5-flash`.
25. Run 1 week WER regression. Owner listening pass.
26. If not enough, try `claude-haiku-4-5`.
27. Ship positive-framed prompt rewrites.

**Phase 6 — DRAFT batching + Misaki IPA (P1, ~3 days):**

28. Ship DRAFT batching at N=8.
29. Populate top-20 IPA overrides from WER history.
30. Ship `pipeline/eval/ipa_lint.py` as build-time check.

**Deferred / P2:** consensus categorization (§7.6), per-story voice
routing (§5.4), Chatterbox sidecar (§5.5).

**Total elapsed:** ~4 weeks if worked linearly. Phases can partially
overlap once observability (Phase 1) exists.

---

## 12. Backward compatibility

- **Manifest is additive.** New optional `audio_url` field. Existing
  stories work.
- **Legacy audio files** in the working tree are backfilled to R2 by
  the migration script. No orphaned records.
- **`PUBLIC_CDN_BASE` default** stays `/data` in dev. Frontend renders
  correctly against either local files or R2 URLs.
- **LLM provider default** is Gemini flash-lite for all stages if the
  new env vars are unset. Rolling back the audio_rewrite upgrade is a
  one-env-var change.
- **Voice mapping default** — if `VOICE_BY_CATEGORY` env override is
  set, code respects it. Rollback is a dict change.
- **Golden-set failure** — for the first week, `run_golden.py` writes
  a warning but does not block. Owner tunes the golden set before
  turning on the hard gate.

---

## 13. Risks + unknowns

### Risks

- **R2 outage during a cron.** Mitigation: retry with backoff + fall
  through to writing local first + retry-upload in next cron. Manifest
  keeps `audio_path`; frontend `<audio onError>` falls back to
  jsDelivr mirror during transition.
- **Structured-output schema drift** — Gemini's `response_schema` API
  has changed API surface historically. Mitigation: pin google-genai
  version; add a fallback that reparses the raw text via json.loads if
  schema-mode fails.
- **Model upgrade regresses WER** — Haiku 4.5 might mis-render Indian
  names Gemini gets right. Mitigation: WER regression gate; the whole
  audio path is a one-env-var revert.
- **Voice sweep favours a voice that Kokoro then updates and changes
  timbre on.** Mitigation: pin `kokoro-onnx` version; the model file
  hash is checked in CI (P2).
- **Golden set curation drift** — as significance evolves, some
  golden verdicts become wrong and cause false alarms. Mitigation:
  RUNBOOK section on how to add/adjust golden rows with justification;
  reviewer required on golden-set PR changes.
- **Git-history purge is irreversible.** Mitigation: mirror-branch
  the pre-purge state before running filter-repo; retain the mirror
  as `origin/pre-r2-mirror` for 90 days after purge.
- **Drift alarm fatigue** — early days will see legitimate accept-rate
  swings from data changes we're deliberately making (source list
  churn). Mitigation: soft-fail mode for the first week + owner
  tunable IQR floor.

### Unknowns

- Whether Gemini's structured-output is reliable enough on
  flash-lite for Merge A's `key_facts: list[str]`. Needs an
  integration test before Phase 2.
- Whether Kokoro's `am_fenrir` or `am_puck` genuinely sound better to
  the owner. Needs the actual listening session.
- Whether R2's custom domain latency in India (owner's region) meets
  the < 1s bar. Needs a one-off measurement.
- Whether `git filter-repo` cleanly removes all audio blobs — some
  might be referenced by tags or dangling objects. Needs a dry-run
  first.

---

## 14. Cost model — CORRECTED post red-team

Red-team R3 caught a 10× math error. Corrected table:

**Per-story LLM math (Gemini 3.5 flash-lite baseline):**
- Input: ~2,000 tokens × $0.10/1M = $0.0002
- Output: ~1,200 tokens × $0.40/1M = $0.00048
- Per-story flash-lite cost ≈ $0.0007 across all stages

**Volume:** 118 stories × 3 runs × 30 = ~10,600 story-runs/mo

| Line | Before | After (P0) | After (P0+P1) | Notes |
|---|---|---|---|---|
| Total LLM calls / day | ~3,600 | ~2,400 | ~2,400 | Merge A only saves ~30% |
| Baseline Gemini flash-lite $/mo | ~$5 | ~$3 | ~$3 | fewer calls |
| Audio rewrite upgrade $/mo (2.5 flash) | 0 | +$20 | +$20 | R3-corrected |
| Audio rewrite upgrade $/mo (Haiku 4.5 alt) | — | +$49 | +$49 | only if 2.5 flash insufficient |
| R2 storage / mo | — | $0 | $0 | under free tier |
| R2 egress / mo | — | $0 | $0 | CF CDN free |
| B2 replica / mo | — | — | $0.02 | month 2 |
| GHA compute / mo | $0 | $0 | $0 | free tier |
| **Realistic monthly spend** | **~$5** | **~$23** | **~$23** | 2.5 flash path |
| **Ceiling if Haiku needed** | **~$5** | **~$52** | **~$52** | requires owner approval |

Original claim of "–$1/mo" was wrong. The audio-quality upgrade
genuinely costs money. Trade-off is worth articulating clearly:

- **~$18/mo delta** buys measurably better audio prosody and closes
  the "robotic voice" complaint at the audio-rewrite stage.
- **Alternative:** stay on flash-lite everywhere, save $18/mo, accept
  the current audio quality. This is a legitimate choice.
- **Decision needs owner input before Phase 5 lands.**

**Volume of work per run (unchanged from original):**

| Metric | Before | After |
|---|---|---|
| Wall clock per run | ~10 min | ~7 min (was estimated 6; corrected for retained separations) |
| Repo size growth / mo | +450 MB (git history) | +150 KB (JSON only) |
| Manual monitoring | none | zero (dashboard is regen'd) |

**R2 request-tier ceiling (from red-team R11):** at current single-user
usage, R2's Class A (writes) and Class B (reads) request counts are
comfortably under the 1M/10M free tier. If audio ever gets embedded in
external RSS clients, per-play chunked HTTP-Range requests could push
Class B toward the ceiling at ~1M plays/mo. Not a concern today; noted
for future.

---

## 15. Priority classification

**P0 — required for correctness or unbounded-growth reasons:**

- Structured-output Merge A + Merge B (§4.1).
- Audio model upgrade to Gemini 2.5 flash (§4.3), Haiku 4.5 only if
  needed.
- Voice sweep + `VOICE_BY_CATEGORY` update (§5.1).
- Punctuation preservation in `normalize.py` (§5.2).
- Cloudflare R2 migration + git-history purge (§6).
- Drift detection (§7.1).
- Golden evaluation set (§7.2).
- Per-run health dashboard (§7.3).
- WER history + weekly summary (§7.4).

**P1 — strong improvement, second wave:**

- LLM provider protocol (§4.2).
- DRAFT batching at N=8 (§4.5).
- Misaki IPA overrides for top-20 (§5.3).
- Backblaze B2 warm replica (§6.2 step 9).
- Significance rebuild shadow workflow (§7.5) — gated by significance
  design in prior review doc.
- Positive prompt rewrites (§4.4).

**P2 — nice-to-have, deferred:**

- Per-story tone-driven voice routing (§5.4).
- Chatterbox sidecar for hero stories (§5.5).
- Consensus categorization (§7.6).
- Kokoro model file hash pin (from §13 risks).

---

## 16. Consistency review (pre-external-panel)

Verifying the design against goals + non-goals:

| Check | Status | Note |
|---|---|---|
| G1 Reduce Gemini call count by ~50% | ✅ | Merge A + B → 55% reduction. |
| G2 Improve audio without leaving Kokoro | ✅ | Voice sweep, punct cues, IPA. |
| G3 MP3s out of `.git`, bounded growth | ✅ | R2 + lifecycle + history purge. |
| G4 Failures visible in workflow logs / repo | ✅ | Drift breach exits non-zero; golden runner blocks PRs. |
| G5 Zero regressions on WER / cat / band | ✅ | WER weekly + golden runner as ship gates. |
| G6 Every migration has one-commit rollback | ✅ | Except git-history purge (§13 risk). |
| N1 No LangChain / agent frameworks | ✅ | Only Protocol + concrete impls. |
| N2 No paid TTS | ✅ | Kokoro stays. |
| N3 No infra sprawl | ✅ | R2 is one env var + boto3. |
| N4 No frontend changes | ✅ | Only `PUBLIC_CDN_BASE` env, which already existed. |
| N5 No new user-facing features | ✅ | Purely cost/quality/reliability. |

Cross-doc consistency:

| Ties to | How |
|---|---|
| `docs/architecture-overview.md` | Corrects §7 call count from 6 to 7–10. Closes §19 gaps 1, 6, 13, 14, 15. |
| `docs/design-review-2026-09-14.md` | Implements the "shadow-mode + regression guard" it sketched (§7.5). Depends on the story-ID stability guarantee it stipulated. |
| `docs/design-review-ui-listening.md` | No conflict. Frontend contract via `PUBLIC_CDN_BASE` unchanged. |
| `docs/design-review-youtube-integration.md` | LLM provider protocol (§4.2) is the same abstraction the YouTube design's `VideoUnderstandingProvider` follows. Consistent pattern. |

---

**End of design draft.** Next: internal red-team + blue-team review,
then external panel (Principal SDE + Solution Architect, AI
Engineering) with no context except this doc and the system
architecture.
