# Backlog — Briefing

**Single source of truth.** Consolidates:

- `docs/design-review-2026-09-14.md` (IA + orthogonal metadata + event clustering + significance rebuild + sports + audio duration + player queue + blog UX)
- `docs/design-review-ui-listening.md` (UX wireframes, mobile, a11y, perf)
- `docs/design-review-youtube-integration.md` (Drishti + Unacademy secondary explainers)
- `docs/design-review-optimization-storage.md` (LLM + audio + storage + observability, post external panel v2)
- Prior sessions' pending items (from `MEMORY.md` project docs)

**Priority scheme:** P0 required · P1 strong improvement · P2 optional
polish · P3 explicitly gated / owner-triggered.

**Status:** `pending` · `in-progress` · `done` · `blocked` · `dropped`.

Any item marked `blocked` names the blocker. Any item marked `dropped`
names the reason. Order within each priority section reflects
sequencing dependencies.

---

## Phase-ordered execution plan

Read the optimization/storage design §11 for the authoritative
sequence. Summary:

**Phase A — Storage first (R2, no purge)** →
**Phase B — Whisper upgrade** →
**Phase C — Audio quality free wins** →
**Phase D — LLM refactor (Merge A only, Gemini-only)** →
**Phase E — Observability spine (soft-fail)** →
**Phase F — Prompt rewrites (isolated commits)** →
**Phase G — Golden set expansion to n≥100** →
**Phase H — Audio model bake-off, gated** →
**Phase I — Advanced items (batching, IPA, significance rebuild)**.

The UI, event clustering, and YouTube designs run in parallel where
they have no infrastructure dependency.

---

## P0 — Required (blocks release quality bar)

### Trivial copy fixes — DO FIRST (from ui-listening §22)

- [x] **B-01** Fix "N°01 / Today" to show only on today's actual lede
  card, not on the first card of every day-group. `site/src/components/Feed.tsx:462-468`.
- [x] **B-02** Fix `refined by hand` copy in `site/src/pages/index.astro:44`
  to something honest — "refined for spoken audio" or similar.
- [x] **B-03** Rename card actions from `read` / `article ↗` to `Read brief` / `Original ↗`. `Feed.tsx:509-517`.
- [x] **B-04** Hero copy — shipped time-of-day framing: "Good {morning|afternoon|evening}. N development(s) to catch you up · M min." Greeting swaps client-side to match viewer's local hour. `index.astro`.

### Sources fixes (from prior session)

- [x] **B-05** Fix 6 dead/blocked feeds in `sources.yaml`: `the_batch` → GN proxy; `sciencedaily_tech` → new path `computers_math/computer_science.xml`; `politico` → `rss.politico.com/politics-news.xml`; `hf_daily_papers` → GN proxy; `moneycontrol_latest`/`moneycontrol_business` → GN proxy.
- [x] **B-06** Add tested-live outlets: Semafor, Rest of World, Yahoo Finance, CNBC Business, Techmeme, `sciencedaily_ai`, `politico_congress`.
- [x] **B-07** Drop hard-paywall proxies from `sources.yaml`: `wsj_gn`, `bloomberg_gn`, `ft_gn`, `the_information_gn`.
- [x] **B-08** Stratechery fail-soft config — keep source, log extract-fails to `data/extraction_failures.jsonl`, don't synth audio when body extraction fails.

### GHA cron hardening

- [x] **B-09** Add `git pull --rebase --autostash` before push step in `.github/workflows/pipeline.yml`.
- [ ] **B-10** Dead-man's-switch: Healthchecks.io free-tier ping at start and end of workflow. Owner set up account + curl in workflow.

### Phase A — Storage migration (S3, NO PURGE — chose AWS S3 over R2 on 2026-09-14)

- [x] **B-11** Write `docs/RUNBOOK.md` §Secrets with rotation cadence (S3 keys 6mo, LLM keys 12mo) + revocation procedure. Rewritten as §S3 on 2026-09-15.
- [x] **B-12** Provision AWS S3 bucket + IAM `briefing-service` scoped to that bucket + $10/mo budget alarm. Done 2026-09-14 in interactive session.
- [x] **B-13** Add S3 secrets to GHA + Vercel: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET`, `S3_REGION`, `PUBLIC_CDN_BASE`. Done 2026-09-14.
- [x] **B-14** Kokoro model file hash pin: CI step that hashes `.models/kokoro-*.onnx` against expected hash from a checked-in `.models/EXPECTED_HASHES.txt`. Fails workflow on mismatch.
- [x] **B-15** `scripts/migrate_audio_to_s3.py` — one-shot backfill preserving `YYYY-MM-DD/*.mp3` key structure with `Cache-Control: public, max-age=31536000, immutable`. (Renamed from `_to_r2.py` on 2026-09-15.)
- [x] **B-16** `pipeline/storage.py` — boto3 S3 upload with post-PUT HEAD + Content-Length verify. On mismatch, retry once, then log to `data/audits/s3_upload_failures-YYYY-MM.jsonl` and fall through to local temp write. Called from `pipeline/tts.py`.
- [ ] **B-17** Run `scripts/migrate_audio_to_s3.py` to backfill existing ~175 MB MP3s. Owner-runnable one-shot.
- [x] **B-18** `.gitignore` — add `site/public/data/audio/*.mp3` and `site/public/data/blogs-audio/*.mp3`.
- [ ] **B-19** R2 lifecycle: news `audio/*` expire 14d, blogs `blogs-audio/*` expire 45d.

### Phase B — Whisper upgrade

- [x] **B-20** Upgrade `pipeline/audio_validate.py` from `tiny.en` to `distil-large-v3`. Re-baseline WER with a 1-day comparison run.
- [x] **B-21** `data/audio_wer_history/YYYY-MM.jsonl` monthly-rotated append in `audio_validate.py`. 6-month in-repo retention.
- [x] **B-22** `pipeline/eval/wer_weekly.py` — Sunday summary buckets by voice/category/story_type; flags p90 > 0.12 or p50 shift > +0.02 WoW.

### Phase C — Audio quality free wins

- [ ] **B-23** `scripts/voice_sweep.py` — generate ≥3 stories × 8 categories × top-5 voices; produce clips in `data/voice_sweep/`.
- [ ] **B-24** MOS-Likert protocol: owner + 1 rater (or owner × 2 sessions ≥ 3 days apart). Ratings written to `data/eval/voice_sweep_YYYY-MM-DD.md`.
- [ ] **B-25** Update `VOICE_BY_CATEGORY` in `pipeline/tts.py` from the published ranking with voice-concentration guard (no voice on ≥ 3 categories).
- [ ] **B-26** AUDIO_REWRITE prompt update: allow `...`, `:`, `—` for prosody; forbid `;` `(` `)`. Deploy 7 days before B-27.
- [ ] **B-27** `pipeline/normalize.py` preservation rules for `...` `:` `—`. Do NOT mechanically add punctuation.
- [ ] **B-28** Characterisation tests for prompt-change surface: 20 fixture stories run through AUDIO_REWRITE; snapshot punctuation distribution; regress on unexpected shifts.

### Phase D — LLM refactor (Gemini-only)

- [ ] **B-29** `pipeline/llm.py` — Gemini-only wrapper. `generate_text()` + `generate_structured()`. Returns `LLMResponse` including `model_version`.
- [ ] **B-30** Log `model_version` on every call to `data/reviews/*.txt`. Weekly fixed-input diff detects silent server-side changes.
- [ ] **B-31** Merge A: `refine._draft + refine._why_matters` into one structured call returning `DraftBundle{draft, stakes}` at T=0.3. Keep `key_points.distill` separate at T=0.0.
- [ ] **B-32** Golden-file diff regression gate: `scripts/refine_replay.py` runs the merged pipeline against 30 days of `data/reviews/`; fails commit if any story judged worse. Owner-review 10 randomly-sampled outputs.

### Phase E — Observability spine (soft-fail)

- [x] **B-33** `pipeline/health.py` renders `data/health/latest.md` + `latest.json` each run. Sections: intake, refine latency, Gemini cost estimate, WER percentiles, run duration, drift status, golden status, R2 upload status. Try/except-wrapped; failure writes `[health] failed at <ts>` line.
- [x] **B-34** `.gitignore` — add `data/health/` and `data/drift/`.
- [x] **B-35** `pipeline/drift.py` writes `data/drift/YYYY-MM-DD.json`. Rolling 7d median + IQR. **Never** `sys.exit(2)`. Informational value in health dashboard.
- [ ] **B-36** `pipeline/eval/golden_set.jsonl` — owner labels first 30 rows (per-category, `label_asof`, bootstrap-CI-ready). SMOKE TEST ONLY at this size.
- [ ] **B-37** `pipeline/eval/run_golden.py` — imports live scorers/classifiers; multi-seed (3×) run; bootstrap CIs; does NOT fail workflow at n=30.
- [ ] **B-38** `data/reviews/` rotation to R2: after 30 days, `pipeline/retention.py` moves to `reviews-archive/YYYY-MM/` in R2. Working tree stays bounded.

### UI — three-level story structure + IA (from design-review-2026-09-14 + ui-listening)

- [x] **B-39** Add `stakes` (from refine layer 2a) as visible "what changed" line on card SCAN. Extract cleanly, don't couple to LLM shape.
- [ ] **B-40** `completed[storyId]` state in localStorage. Mark on audio end OR brief-expanded > 15s. Card renders at 0.7 opacity when completed; cover greyscaled.
- [x] **B-41** "You're caught up" plate at bottom of feed when new_since is empty. Reuses existing empty-plate component.
- [ ] **B-42** Sectioned feed: CATCH UP / WORTH KNOWING / YOUR BEATS / EXPLORE / ARCHIVE. Requires `lastVisitAt` state. Extract into `<CatchUp />`, `<WorthKnowing />`, etc.
- [ ] **B-43** Mobile bottom-bar player (76 px) + bottom-sheet expansion with next/prev/speed/queue/close.
- [ ] **B-44** Player queue: `▶ Play catch-up` from CATCH UP header. Composes per-story MP3s. `localStorage.briefing.queue`.

---

## P1 — Strong improvement

### Content pipeline

- [x] **B-45** Rule-based audio scorers (`pipeline/eval/audio_scorers.py`): numeric preservation, acronym coverage, forbidden-punct count, sentence-length distribution, attribution presence. Ships in Phase C alongside voice sweep.
- [x] **B-46** AUDIO_REWRITE in-prompt worked example (`$2.3B revenue → two point three billion dollars`). Phase F.
- [x] **B-47** DRAFT deterministic length parameter: `target_words = clamp(source_words × 0.35, 150, 360)`. Phase F.

### Orthogonal metadata + event clustering (from design-review-2026-09-14)

- [ ] **B-48** Extend `pipeline/categorize.py` prompt to emit `topics[]`, `entities[]`, `regions[]`, `story_type`, `impact_scope`, `importance`, `persona_relevance{india, technology, business}`.
- [ ] **B-49** Add sports-only fields when `main == SPORTS`: `sport`, `competition`, `competition_stage`, `athletes_or_teams[]`.
- [ ] **B-50** Backfill script `pipeline/backfill_metadata.py` — re-categorize current 7-day retention window with new fields.
- [ ] **B-51** `pipeline/cluster.py` — Stage 2 event/development classifier over MiniLM candidate pairs. Emits `SAME_EVENT_SAME_DEV`, `SAME_EVENT_NEW_DEV`, `DIFFERENT_EVENT`.
- [ ] **B-52** `data/clusters.json` cluster table with 30-day active window.
- [ ] **B-53** `event_id` + `event_update_type` on stories. Cross-source enrichment (PLAN C4): SAME_EVENT_SAME_DEV → merge + append `sources[]`.

### Significance rebuild (from design-review-2026-09-14 §8, canary set from Solution Architect)

- [ ] **B-54** `pipeline/significance_v3.py` — remove T1 actionability penalty. Add `consequence`, `novelty_of_fact`, `scale_of_impact`, `lasting_importance` signals. Weighted score formula.
- [ ] **B-55** `pipeline/eval/canary_significance.jsonl` — 20 hand-labelled stories with owner-desired rank order.
- [ ] **B-56** `pipeline/eval/shadow_diff.py` — Spearman ≥ 0.85 AND Kendall's τ ≥ 0.7 AND per-decile agreement ≥ 80%. Gates flip from v2 → v3.
- [ ] **B-57** Sports scoring via orthogonal metadata (`sport_priority × competition_priority × indian_athlete`) — from ui-listening §11.

### UI — Level 3 depth, event timeline, sports/india lenses

- [ ] **B-58** Level-3 CONTEXT/TIMELINE/ALL SOURCES rendering. Only for stories with `event_id` + cluster ≥ 2, or `enrichment_deltas[]`.
- [ ] **B-59** Sports "For You" sub-tab combining badminton + athletics + running + marathons + cricket + F1 + Indian-athlete stories.
- [ ] **B-60** INDIA relevance lens: cross-category chip filtering to `regions.includes("IN") || persona_relevance.india ≥ 0.6`.
- [ ] **B-61** Globe demoted to Explore-mode toggle. Lazy-load only when requested.
- [ ] **B-62** Playback speed control (0.9× · 1.0× · 1.15× · 1.25× · 1.5×). Client-side `audio.playbackRate` only.
- [ ] **B-63** Queue drawer: desktop `Q` shortcut, mobile bottom-sheet. Drag-to-reorder. localStorage-persistent.

### Blog UX

- [ ] **B-64** Always-visible `summary_short` hook on blog cards (2–3 line clamp).
- [ ] **B-65** Listen button on blog card (move from expanded body).
- [ ] **B-66** "Recommended this week" horizontal shelf at top of `/blogs`. 3 entries by rotation-freshness × topic-balance × source-diversity.
- [ ] **B-67** Weekly cron for `blogs_run.py`. Sunday 09:00 UTC.

### Observability (upgrades)

- [ ] **B-68** Golden set expansion to n≥100 with per-category stratification. Owner-effort. Unlocks hard-fail gate.
- [ ] **B-69** Golden set hard-fail gate flip: `run_golden.py` exits non-zero on cat < 85%, band < 80%, decision < 90% (all bootstrap-CI adjusted).
- [ ] **B-70** Distributional drift statistic — KS-test or binned-histogram delta on score distribution (upgrade over accept-rate).
- [ ] **B-71** Backblaze B2 warm replica of R2: nightly rclone sync. Fallback if R2 has an incident.

### Copy + accessibility

- [ ] **B-72** Full accessibility pass: landmark roles, keyboard walk (Tab/Space/Enter/Left/Right/Q/Esc), aria-labels on player/sources chip/timeline/LIVE dot, `prefers-reduced-motion` extension to layout-shared transitions and NowPlayingWave, contrast audit for age-dimmed cards.

---

## P2 — Optional / gated

- [ ] **B-73** Audio model bake-off (Phase H): flash-lite vs 2.5-flash vs Haiku-4.5 vs Sonnet-4.5 (ceiling). Rule-based scorers + LLM-as-judge pairwise blinded (Sonnet judge). Owner explicit approval before spending +$20/mo.
- [ ] **B-74** DRAFT batching at N=8 with fuzz test: 1 of 8 malformed × 100 batches, verify per-story fallback recovers 100%.
- [ ] **B-75** Misaki IPA overrides for top-20 mispronunciations. Requires 14 days of WER history first. Includes IPA-lint build check.
- [ ] **B-76** Consensus categorization (T=0.0 + T=0.3, only accept when both agree). Gated on n≥100 golden set.
- [ ] **B-77** `promptfoo` or `DeepEval` migration spike. 1-week prototype; adopt only if setup < 2h and output at least as informative.
- [ ] **B-78** LLM-as-judge for content quality on AUDIO_REWRITE stage. Sonnet 4.5 as judge. ~$5–10/mo when running.
- [ ] **B-79** Per-story tone-driven voice routing. Requires refine to emit `tone` field.
- [ ] **B-80** Chatterbox sidecar for top 1–2 hero stories/day. 8GB VRAM self-host. Only if Kokoro path insufficient.
- [~] **B-81** YouTube integration (Drishti + Unacademy). Scaffold shipped 2026-09-15: `pipeline/youtube_sources.yaml` (both channels, disabled), `pipeline/youtube.py` (stages A-F pure fns + seen-state), `pipeline/video_understanding.py` (`VideoUnderstandingProvider` interface + `GeminiVideoProvider` with transcript-focused prompt). Not yet wired into run.py — needs `YOUTUBE_API_KEY` secret + shadow-eval week before flipping `enabled: true`.
- [ ] **B-82** Positive/uplift tone facet chip in UI (needs `tone` field).
- [ ] **B-83** arXiv paper ranker — only surface when a Tier-A desk has cited.
- [ ] **B-84** Uber Engineering blog needs GN proxy fallback.
- [ ] **B-85** Peter Norvig blog (no live RSS) — skip until he adds one.
- [ ] **B-86** Blog entry cover art via `AbstractCover`.
- [ ] **B-87** Google News as first-class source (owner asked).
- [ ] **B-88** Reddit source enable (OAuth pending).
- [ ] **B-89** Gmail source enable (OAuth read-only + sender allowlist).

---

## P3 — Explicitly gated / owner-triggered

- [ ] **B-90** **Git-history purge** — moved to `docs/OPT-IN-OPERATIONS.md`. Only runs when owner declares "the 588 MB is causing observable pain." Includes preconditions, procedure, rollback via `pre-r2-purge` tag.
- [ ] **B-91** VERCEL_TOKEN rotation cadence (no-expiry token created 2026-09-14 per owner note; document in RUNBOOK).

---

## Dropped items (with reason)

- ~~Merge B (audio_rewrite + sanity self-check)~~ — external panel: circular validation + $1/mo savings not worth ceremony.
- ~~LLMProvider Protocol with three provider stubs~~ — Principal SDE: no code shipped that CI can't test. Gemini-only wrapper instead (B-29).
- ~~Drift `sys.exit(2)` on IQR breach~~ — external panels: known 5–15% false-alarm from calendar variance. Informational only (B-35).
- ~~Golden set n=30 as hard-fail gate~~ — external panels: ±13pp Wilson CI at n=30 cannot arbitrate the thresholds. Smoke test only until n≥100 (B-68/B-69).
- ~~Audio model upgrade as P0~~ — Principal SDE §2.3: free wins must be tried first. Deferred to P2 (B-73).

---

## Meta

- **Reviewed by:** owner (self), red-team (Claude), blue-team (Claude), Principal SDE (Claude external), Solution Architect AI Engineering (Claude external).
- **Design freeze:** 2026-09-14.
- **Total items:** 91.
  - P0: 44
  - P1: 28
  - P2: 17
  - P3: 2
- **Dropped items:** 5 (documented above).
