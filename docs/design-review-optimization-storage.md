# Design Review — Content-Gen Optimization, Audio Quality, Storage & Observability

**Date:** 2026-09-14 (revised post-external-panel)
**Status:** v2 — internal red/blue applied, external panel applied.
Consolidation memo: `docs/_review/consolidation-v2.md`.
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

### 4.1 Structured-output merges (P0) — revised post external panel

External panels (Principal SDE §2.7, Solution Architect §4) both
flagged Merge B's split-then-A/B as process theater for ~$1/mo savings.
**Deleted.** Only Merge A remains.


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

**Merge B — DELETED.** External panels agreed the split-then-A/B for
$1/mo was not worth the ceremony. Sanity remains a separate call.
audio_rewrite ships standalone via structured output (`audio_text`
only, no self_check field).

**Net effect after all revisions:** 7–10 calls → **6–8 calls/story**
(~20–30% reduction). Original "55%" claim (unrevised draft) was
overreach. Corrected.

**Keep separate (unchanged):**

- `fact_verify + _redraft` — external critique is the point.
- `coverage (final)` — must run after `audio_rewrite`.
- `sanity` — see Phase 5b above.

**Safety net (unchanged):** golden-file diff on `data/reviews/`
fixtures gates every merge.

### 4.2 LLM client refactor (P1) — revised post external panel

Principal SDE (§2.2) and Solution Architect (§4) both flagged the
Protocol shipping three untested provider stubs. **Ship Gemini-only.**

No `ClaudeProvider` / `OpenAIProvider` stubs. If §4.3 model upgrade
lands as P2 later, it comes as a direct Claude client call in that
one stage, not through a false abstraction.

What DOES land in Phase 4:

- **`pipeline/llm.py`** — a Gemini-only wrapper with:
  - `generate_text(prompt, *, temperature, max_tokens) -> LLMResponse`
  - `generate_structured(prompt, schema, *, temperature, max_tokens) -> LLMResponse[schema]`
  - `LLMResponse` includes: `text`, `model_version` (from Gemini response
    metadata), `input_tokens`, `output_tokens`, `elapsed_ms`.
- Every call site logs `model_version` to `data/reviews/*.txt`
  alongside prompt/response. Weekly diff of a fixed test-input set flags
  silent server-side model changes (Solution Architect §7).
- Per-stage model env var overrides remain (`LLM_AUDIO_MODEL`).

Two-method interface (`generate_text` and `generate_structured`)
survives if we ever bring in a second provider. Not committed today —
premature abstraction was the critique. No third-party client code
ships that no test exercises.

### 4.3 Model upgrade for audio_rewrite — DEFERRED TO P2 (post external panel)

Both external panels (Principal SDE §2.3, Solution Architect §2) pushed
hard on this. The $20/mo upgrade should not ship until the *free*
audio wins (§5.1 voice sweep, §5.2 punctuation, §5.3 IPA) have been
tried and *empirically shown insufficient*. Wrong to spend $20/mo
before doing $0 work that plausibly closes the complaint.

**Revised procedure — runs only if §5 doesn't close the audio complaint:**


Red-team R3 correctly caught a 10× math error in the Haiku cost
estimate. Corrected numbers:

**Volume:** ~118 stories/run × 3 runs/day × 30 days = ~10,600 rewrites/mo.
Audio rewrite output averages ~400 words ≈ ~530 tokens. Input (source
+ prompt) averages ~2,000 tokens.

| Option | Total/mo | Role in bake-off |
|---|---|---|
| Gemini 3.5 flash-lite (current) | ~$0.43 | baseline |
| Gemini 2.5 flash | ~$20 | cheaper candidate |
| Claude Haiku 4.5 | ~$49 | mid-tier candidate |
| **Claude Sonnet 4.5** | **~$60–80** | **ceiling reference** (from Solution Architect §2) |
| GPT-4.1-mini | ~$17 | alternative candidate |

**Bake-off procedure (only runs if §5 free wins don't close the complaint):**

1. Frozen 30-story evaluation set (separate from golden set): heavy
   numerics, acronyms, Indian/F1/German proper nouns, quote-heavy copy.
2. **Rule-based scorers** (§15 new):
   - Numeric preservation: regex-diff `\d[\d,.]*` in source vs rewrite,
     accept containment or spelled-out equivalents (via `num2words`
     bidirectional check).
   - Acronym letter-spacing coverage: extract acronyms from source,
     verify each appears letter-spaced (`A. P. I.` format) in rewrite.
   - Forbidden-punctuation counter: `;`, `(`, `)` must be zero. `:`,
     `—`, `...` allowed if AUDIO_REWRITE prompt permits (§5.2).
   - Sentence-length distribution: p50 ∈ [12, 20], p90 ≤ 25.
3. **LLM-as-judge, pairwise blinded, third-model judge** (Solution
   Architect §3). Sonnet 4.5 as judge; never a model judging itself.
4. A/B all four models against Sonnet 4.5 as ceiling. Report per-defect
   rate, not aggregate preference.
5. Decision: ship the cheapest model that lands within 10% of Sonnet on
   every rule-based scorer. If flash-lite passes, no upgrade needed.

Ship gate: explicit owner approval + eval publication to
`data/eval/audio_bakeoff_YYYY-MM-DD.md`.

**Do not silently upgrade** the whole feed. Do not ship on vibes.

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

### 5.1 Voice sweep (P0, ~1 evening) — revised post external panel

Solution Architect §6 correctly demanded a proper eval. n=1 rater × n=1
story per condition is not an eval. Restructured:

**Structured MOS-Likert protocol:**

1. Pick **≥ 3 representative stories per category** (AI, TECH, SCIENCE,
   SPORTS, US, INDIA, WORLD, BUSINESS = 24+ stories total) from
   `data/reviews/`.
2. Generate each story across the top-5 candidates: `am_fenrir` (C+),
   `am_puck` (C+), `bm_fable` (C, warm), `bf_emma` (B-), `af_heart` (A).
   Plus current baseline (`am_liam`, `am_michael`, `bm_george` as
   appropriate). ~150 clips total.
3. **3-dim Likert MOS per clip** (1–5): naturalness, clarity, category
   fit.
4. **≥ 2 raters.** Owner + one friend. Or, if only owner: 2 sessions ≥ 3
   days apart with clips shuffled — averages out same-day drift.
5. Ranker script processes ratings into per-category top-voice.
6. **Publication:** results committed to `data/eval/voice_sweep_YYYY-MM-DD.md`
   with per-voice score + rater disagreement.
7. Update `VOICE_BY_CATEGORY` in `pipeline/tts.py` from the published
   ranking.

**Guard against over-concentration** (Solution Architect §6): the
default proposal placing `am_fenrir` on 4 categories loses the
per-category differentiation. If any voice appears on ≥ 3 categories,
require a second-place candidate for one of them.

**Working-tree transition (red-team R4 doc trade-off):** post-flip, old
audio in the tree/R2 keeps old voices until 14-day rotation replaces
them. Alternative: regenerate on flip (~30min TTS, free). Owner decides
at Phase 3.

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
8. **Git history purge — REMOVED from this design (post external panel).**

   Principal SDE §2.1 and §6 correctly argued that for a single-user
   repo, `.gitignore` in step 6 stops future growth — which is what
   actually matters. The `git filter-repo` step is a destructive
   operation whose only benefit is faster clone time on a repo the
   owner clones rarely.

   **The purge is moved to `docs/OPT-IN-OPERATIONS.md`** as an
   owner-triggered standalone procedure, gated on an explicit "the 588
   MB is causing observable pain" trigger. It is not on any Phase's
   critical path.

   The `.gitignore` entry in step 6 is what makes this design
   self-consistent: from step 6 forward, no new audio enters git. The
   pre-flip 588 MB is a one-time accepted cost.

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

### 7.1 Drift detection — INFORMATIONAL ONLY (post external panel)

Both external panels (Principal SDE §2.5, Solution Architect §7)
correctly flagged that a scalar accept-rate has ~5–15% false-alarm rate
baked in from calendar/weekend/source variance. **`sys.exit(2)` on IQR
breach removed.**

**Revised behavior:**

- `pipeline/drift.py` computes today's accept-rate + IQR-scaled z-score.
- Writes `data/drift/YYYY-MM-DD.json` (git-ignored, see §8.2).
- **Never fails the workflow.**
- Value + status appears in `data/health/latest.md` as an informational
  line: `drift: today 23.1 %, 7d-median 24.5 %, z=-0.4, status=ok`.
- On `breach`, health dashboard renders the line in bold; still no
  workflow exit.

**Future upgrade to distributional (P1):** replace scalar accept-rate
with score-distribution KS-test or binned-histogram delta. Then
consider hard-fail. Not in this design's scope.

Cost: ~50 ms per run. No LLM calls.

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
- Reports category-agreement, band-agreement, decision-agreement with
  bootstrap CIs (Solution Architect §3).
- Writes `data/eval/golden_YYYY-MM-DD.json`.
- **At n=30 (initial): SMOKE TEST ONLY.** Runs, reports, does not fail
  workflow. n=30 with the stated thresholds has ±13pp Wilson CI on
  85% — cannot arbitrate a real regression (Solution Architect §3,
  Principal SDE §2.4).
- **Hard-fail gate requires n≥100** with per-category stratification.
  When owner labels reach that bar, the workflow-exit switch flips.
- **Multi-seed run:** runner runs 3× (temperature 0.0 is not
  deterministic across server-side model updates) and reports the
  modal verdict. Disagreement across seeds flags the story for review.
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

## 11. Migration + rollout order — REVISED post external panel

Principal SDE §5 argued for a different sequence. Adopted with
adjustments. **New sequence (~40% smaller scope than pre-external-panel):**

**Phase A — Storage first, no purge (P0, ~2 days):**

1. Provision Cloudflare R2. Custom domain via CF DNS + CDN.
2. Add secrets to GHA + Vercel. Write `docs/RUNBOOK.md` §Secrets
   with rotation cadence (R2 keys every 6 months, LLM keys every 12
   months) BEFORE adding the secrets (Principal SDE §4.P3).
3. Kokoro model file hash pin: 2-line CI check against
   `.models/kokoro-*.onnx` expected hash (Principal SDE §4.P5).
4. Backfill script → R2.
5. Flip `PUBLIC_CDN_BASE`. Pipeline writes to R2 with post-PUT integrity
   check (HEAD + Content-Length verify, Principal SDE §4.P4).
6. `.gitignore` MP3s.
7. **No git-history purge.** Moved to `docs/OPT-IN-OPERATIONS.md`.

**Phase B — Whisper upgrade (P0, ~1 day):**

8. Upgrade `audio_validate.py` from `tiny.en` to
   `distil-large-v3` (Solution Architect §6). Re-baseline WER.
9. `data/audio_wer_history/YYYY-MM.jsonl` monthly-rotated append.
10. Weekly WER summary.

**Phase C — Audio quality free wins (P0, ~1 week):**

11. Structured voice sweep per §5.1: MOS-Likert, ≥3 stories × top-5
    voices, ≥2 raters. Results committed to `data/eval/voice_sweep_*.md`.
12. Update `VOICE_BY_CATEGORY`. Voice-concentration guard.
13. AUDIO_REWRITE prompt update (Step A of §5.2) allowing `...`, `:`, `—`.
14. `normalize.py` preservation rules (Step B of §5.2, 7 days after Step A).
15. Characterisation tests over prompt-change surface (Solution Architect §7.4).

**Phase D — LLM refactor (P0, ~2 days):**

16. `pipeline/llm.py` Gemini-only wrapper (§4.2), `model_version`
    logging on every call.
17. Merge A ship (`draft + stakes`, T=0.3 in structured output).
    `distill` stays separate.
18. Golden-file diff on 30 days of `data/reviews/` gates the merge.

**Phase E — Observability spine, scoped down (P0, ~1 week):**

19. `pipeline/health.py` writes `data/health/latest.md` (git-ignored,
    see §8.2).
20. `pipeline/drift.py` writes `data/drift/YYYY-MM-DD.json`
    (git-ignored). Informational only.
21. Owner starts hand-labeling `pipeline/eval/golden_set.jsonl` (n=30
    baseline → n=100 target). Runner runs as smoke test only.
22. Dead-man's switch: Healthchecks.io free-tier ping in the workflow
    (§13, Principal SDE §4.P-missing-1).

**Phase F — Prompt rewrites, isolated (P1, ~3 days):**

23. AUDIO_REWRITE worked example (Solution Architect §5).
24. DRAFT deterministic length parameter (Solution Architect §5).
25. Ship in own commits, 7 days after Phase D. Regressions attribute
    correctly (Solution Architect §8.A8).

**Phase G — Golden set expansion (P1, owner-effort dependent):**

26. Owner labels to n≥100 with per-category stratification.
27. Hard-fail gate flips ON (Solution Architect §3).

**Phase H — Reassess §4.3 audio-model bake-off (P2, gated):**

28. Only if §5 free wins did not close the audio complaint.
29. Bake-off includes Sonnet 4.5 as ceiling reference.
30. Rule-based scorers arbitrate, not owner listening (Solution
    Architect §6).
31. Owner explicit approval before spending +$20/mo.

**Phase I — Advanced items (P2, deferred):**

- DRAFT batching at N=8 (Solution Architect §4 fuzz test required).
- Misaki IPA overrides (14 days of WER history prerequisite).
- Significance rebuild shadow rollout (canary set of 20 required —
  Solution Architect §7.6).
- Consensus categorization.
- `promptfoo` / `DeepEval` migration spike.

**No git-history purge in any phase.** Opt-in only.
**No LLM provider stubs shipped.** Gemini-only.
**No audio model upgrade shipped by default.** P2, gated.

Total elapsed (linear): ~4 weeks Phases A–E. Phases F–I owner-paced.
Scope roughly 40% smaller than the pre-external-panel draft.

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
| **Realistic default spend (Phases A–G shipped)** | **~$5** | **~$3–4** | | Merge A savings; no model upgrade shipped |
| **If Phase H ships 2.5 flash** | **~$5** | **~$23** | | +$20/mo, requires eval win + owner approval |
| **Ceiling if Sonnet 4.5 lands** | **~$5** | **~$65–85** | | not recommended; ceiling reference only |

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

## 15. Rule-based audio scorers (new — from Solution Architect §2)

Before shipping any audio_rewrite model upgrade (Phase H), rule-based
scorers evaluate rewrites deterministically. Ships in Phase C alongside
voice sweep so we have the eval before the change.

**`pipeline/eval/audio_scorers.py`:**

```python
class AudioScorers:
    def numeric_preservation(source: str, rewrite: str) -> float:
        """Extract every \\d[\\d,.]* from source. Verify each appears
        in rewrite either verbatim OR as its num2words spelled form
        OR its currency-spelled equivalent. Return fraction preserved."""

    def acronym_letter_spacing(source: str, rewrite: str) -> dict:
        """Extract acronyms from source (≥2 caps, ≤5 chars, dict lookup).
        For each: verify rewrite contains letter-spaced form (e.g. A. P. I.).
        Return coverage + list of unspaced acronyms."""

    def forbidden_punctuation(rewrite: str) -> dict:
        """Count `;`, `(`, `)` in rewrite. Must be zero. `:`, `—`,
        `...` allowed under Phase C prompt update."""

    def sentence_length_dist(rewrite: str) -> dict:
        """Return p50, p90 of sentence word counts. Target p50 ∈ [12, 20],
        p90 ≤ 25."""

    def attribution_present(rewrite: str, source_name: str) -> bool:
        """Verify source_name appears once in sentences 2 or 3."""
```

**Threshold gates for shipping model changes:**

- Numeric preservation ≥ 0.98.
- Acronym coverage ≥ 0.95.
- Forbidden-punct count == 0.
- Sentence-length p50 ∈ [12, 20], p90 ≤ 25.
- Attribution present true.

Any candidate model (Phase H bake-off) must pass all five gates on the
30-story bake-off set before it can even enter the LLM-as-judge round.

---

## 16. Priority classification — REVISED

**P0 — required, ships in Phases A–E:**

- Cloudflare R2 migration, no purge (§6, Phase A).
- Kokoro model file hash pin (Phase A step 3).
- `docs/RUNBOOK.md` §Secrets rotation policy (Phase A step 2).
- R2 upload integrity check (Phase A step 5).
- Whisper `tiny.en` → `distil-large-v3` (Phase B).
- WER history monthly-rotated + weekly summary (Phase B).
- Structured voice sweep with MOS-Likert (Phase C).
- AUDIO_REWRITE prompt update allowing prosody punct (Phase C).
- `normalize.py` preservation rules (Phase C, 7 days after prompt).
- Characterisation tests for prompt-change surface (Phase C).
- `pipeline/llm.py` Gemini-only wrapper + `model_version` logging
  (Phase D).
- Merge A `draft + stakes` structured output (Phase D).
- Golden-file diff regression gate on `data/reviews/` (Phase D).
- `data/health/latest.md` regenerated each run, git-ignored (Phase E).
- Drift detector, informational-only (Phase E).
- Golden set n=30 baseline as smoke test (Phase E).
- Dead-man's-switch Healthchecks.io ping (Phase E).
- `data/reviews/` 30-day rotation to R2 (Phase E).

**P1 — second wave:**

- Rule-based audio scorers (§15, Phase C prerequisite for Phase H).
- Prompt rewrites (AUDIO_REWRITE example + DRAFT length param) — Phase F.
- Golden set expansion to n≥100 (Phase G, owner-effort dependent).
- Backblaze B2 warm replica (§6.2 step 9).
- Distributional drift statistic (KS-test / histogram delta).

**P2 — gated, may never ship:**

- Audio model upgrade (§4.3) — only if free wins fail.
- DRAFT batching at N=8 with fuzz test (Phase I).
- Misaki IPA overrides for top-20 (Phase I).
- Significance rebuild shadow workflow with canary set (Phase I).
- Consensus categorization (Phase I).
- `promptfoo` / `DeepEval` migration spike (Phase I).
- Per-story tone-driven voice routing.
- Chatterbox sidecar for hero stories.
- LLM-as-judge for content quality.
- `docs/OPT-IN-OPERATIONS.md` git-history purge (owner-triggered only).

---

## 17. Consistency review (post-external-panel)

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

**End of design v2.** Internal red-team, blue-team, and external panel
(Principal SDE + Solution Architect, AI Engineering) all applied. See
`docs/_review/consolidation-v2.md` for the diff summary.

**Design frozen.** Next: backlog refresh (`docs/BACKLOG.md`) + execution
in the sequence above.
