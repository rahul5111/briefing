# External Principal SDE Review — Optimization / Storage / Observability

**Reviewer:** Principal SDE, 15+ yrs HA / cost / reliability.
**Scope reviewed:** `architecture-overview.md`, `design-review-optimization-storage.md`, red-team + blue-team.
**Stakes:** single-user product, ~$5/mo run rate today, one owner.

---

## 1. Overall verdict

**Accept with revisions.** The red/blue pass already fixed the worst
math and sequencing errors. What remains is mostly a scope problem: for
a single-user briefing tool, this design is roughly 2x the machinery
that's warranted. Three items below need to change before shipping;
the rest is negotiable but the owner should know they're paying a
complexity tax that a stricter reviewer would refuse.

---

## 2. Materially wrong items

1. **[Critical] §6.2 step 8 — the "one-way" purge is still not safe.**
   The revised precondition list (14 days on R2, tag, mirror, workflow
   in `workflow_dispatch`, cleared Vercel cache) is decent, but it
   misses the loudest failure mode: **`git filter-repo` rewrites every
   commit SHA in history**, and Vercel's project-linking, deploy
   protection, and any downstream artifact (RSS `<guid>` values that
   embed a commit URL, jsDelivr CDN URLs that pin to a SHA) will silently
   404 or double-serve. The RUNBOOK also has no explicit "verify
   `origin/HEAD` is the rewritten history on GitHub *before* deleting
   the mirror" step, and no smoke test for the Vercel *production*
   deployment against the rewritten history (only "build cache
   cleared"). If Vercel's link is by project ID it survives; if any
   webhook or GHA step references a pre-purge SHA (checkout of a
   specific commit for a scheduled backfill, for example), it dies at
   the next trigger. **Fix:** add a step 8.5 "run the full pipeline on
   the rewritten repo end-to-end and confirm a successful prod deploy"
   before deleting the mirror or re-enabling cron. Also: this doesn't
   need to happen at all — see §6 below.

2. **[Major] §4.2 LLMProvider Protocol is under-specified and blue team
   waved it through.** The signature `generate(prompt, *, schema,
   temperature, max_tokens) -> str | T` collapses three provider
   surfaces that are not interchangeable in the ways the design needs.
   Concrete leaks: (a) Gemini `response_schema` silently drops fields
   it can't fit; Claude tool-use raises; OpenAI `response_format`
   requires `additionalProperties: false` and rejects `Optional[...]`
   patterns that Pydantic emits by default. (b) Rate-limit and retry
   semantics differ (Gemini's 429 body is structured, Anthropic's isn't
   in older SDKs, OpenAI uses headers). (c) `max_tokens` means different
   things across providers when structured output is on. Returning
   `str | T` is a type-union that every call site has to disambiguate.
   Blue team's answer ("Protocol is best-effort, acknowledged abstraction
   leak") is a cop-out — an acknowledged leak is still a leak. **Fix:**
   either narrow the Protocol to `generate_structured(prompt, schema) ->
   T` and `generate_text(prompt) -> str` as two methods, or admit this
   is Gemini-only with placeholder classes for the other two and stop
   pretending it's a real abstraction. Do not ship three provider stubs
   you cannot test.

3. **[Major] §4.3 — the audio-model upgrade is not the right call for
   this product.** +$20/mo is a 4x run-rate increase for a *single
   listener* who has already accepted Kokoro TTS's ceiling. The design
   defends it as "the highest-leverage quality change," but the actual
   evidence is: two Kokoro voices are D-grade (fixed free by §5.1),
   punctuation is stripped by the current prompt (fixed free by §5.2),
   240 pronunciation rules exist but IPA overrides don't (fixed free-ish
   by §5.3). The audio-rewrite *prompt* has never been isolated as the
   quality bottleneck vs. the *TTS engine*. Doing §5.1–5.3 first and
   then reevaluating is the correct sequence; instead §4.3 sits in
   Phase 5 as a P0. **Fix:** downgrade §4.3 to P2. Reassess after §5
   lands. Ship it only if owner blind-listen after §5.1–5.3 still
   flags the rewrite as the weak layer.

4. **[Major] §7.2 golden set — 30 rows, hand-labeled once, is not a
   regression gate.** Category-agreement at 85% on 30 rows means a swing
   of 5 rows moves you from pass to fail; that's inside noise. Band-
   agreement at 80% on 30 rows with 5 boundary examples is worse — one
   boundary flip is a 20% delta. Red team caught the time-anchor issue
   but not the sample-size issue. The blue-team-added "PR justification
   required for edits" makes this worse: it discourages the exact
   frequent re-labeling that a small golden set needs to stay honest.
   **Fix:** either commit to a minimum of ~100 labels before turning
   the hard gate on, or acknowledge this is a smoke test, not a
   regression gate, and don't wire it into the workflow exit code.

5. **[Major] §7.1 drift detector on daily accept-rate is the wrong
   signal.** Accept-rate is a scalar summary of a filter's output; it
   moves for a hundred reasons that have nothing to do with regression
   (news volume, weekend cycles, source-list churn, dedup rate on hot
   news days). Red team caught the source-fix collision; the deeper
   issue is that IQR-band on 7-day median with a single scalar has
   ~5–15% false-alarm rate baked in from calendar variance alone. A
   correct drift signal is on the *score distribution* (KS-test or
   binned histogram delta), not on a single count. **Fix:** either
   accept this is a smoke alarm not a drift alarm and rename it, or
   compute a distributional statistic. The `sys.exit(2)` on breach as
   currently designed will fail the workflow on ordinary Saturdays.

6. **[Minor] §7.3 health dashboard as markdown-in-git.** Regenerated
   every run and committed. That's the exact pattern that grew `.git`
   to 588 MB — small, frequent commits of derived data. At ~15 KB/run x
   3/day x 365 = ~16 MB/year, in git, forever. It's bounded but it's
   the same anti-pattern the design is elsewhere trying to fix. **Fix:**
   write it to `data/health/` but git-ignore it (or write to R2). The
   value is "did owner glance at it this morning," not history.

7. **[Minor] §4.1 Merge B split-then-maybe-merge is process theater.**
   Phase 5a ships audio_rewrite standalone; Phase 5b "runs one week of
   dual output" to decide whether to merge sanity. That's a whole week
   of extra Gemini calls to save one call. The savings from Merge B
   consolidation (if it works) is roughly $1/mo at this volume. Not
   worth an A/B. **Fix:** ship 5a. Don't schedule 5b. Revisit only if
   volume grows 10x.

---

## 3. Legitimately good decisions

1. **Deferring Chatterbox + per-story tone routing to P2 (§5.4, §5.5).**
   Correctly identified as scope creep. Kept in the doc, kept out of
   the phase plan.
2. **Golden-set `label_asof` field (§7.2, post-R8).** This is the right
   design for a stable eval set against a time-sensitive filter. Even
   at 30 rows the shape is correct.
3. **Prompt-before-normalizer sequencing in §5.2 (post-R5).** Blue team
   got this right. It's the difference between the pipeline working
   and mechanically re-adding punctuation the LLM was told to strip.
4. **Cost math correction in §14 (post-R3).** Going from "–$1/mo" to
   "+$18/mo, explicit owner approval" is exactly the honesty a design
   should have. Even though I think §4.3 is wrong on merits (see
   Materially Wrong #3), the *disclosure* is now honest.
5. **R2 choice for object storage (§6.1).** Zero-egress via Cloudflare
   CDN + S3-compatible API is genuinely the right pick for a
   read-mostly single-user corpus. Not Backblaze, not S3 with
   CloudFront.
6. **Observability self-failure guards (§7.3, §7.4, post-R9).**
   `[health-render] failed at <ts>` line is the correct pattern. Cheap,
   loud, right.

---

## 4. Missing considerations (neither doc caught)

1. **No secret-rotation story despite two `VERCEL_TOKEN` expirations
   already.** Architecture §10 flags this as known pain and roadmap
   item #7. The design adds *six* new secrets
   (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_BUCKET`, `R2_ENDPOINT`, `R2_PUBLIC_BASE`) plus potentially two
   more LLM API keys. The blast radius of a leaked R2 secret is a
   public-write bucket at Cloudflare's request tier. No design section
   covers rotation cadence, no `docs/RUNBOOK.md` is scoped beyond "R2
   credential rotation, manual." This is silently making the "silent
   token expiry" bug worse.
2. **No integrity check on R2 uploads.** boto3 puts objects; no
   ETag/MD5 verification, no re-fetch-and-hash. If R2 stores a
   corrupted body (rare but real for CDN-fronted PUT), you'll find out
   from your ears, not from the pipeline. Add a post-upload HEAD +
   size check at minimum.
3. **No dead-man's switch.** Cron failing silently is the actual
   user-visible failure mode. The design adds drift and golden gates
   that *can* fail the workflow, but nothing alerts the owner that
   *the workflow didn't run at all*. A missed 02:00 UTC cron with no
   notification is indistinguishable from a boring day. A one-line
   healthcheck ping (Healthchecks.io free tier, or a Vercel serverless
   fn that checks `feed.json` mtime) closes this.
4. **Kokoro model file pin is P2 but is a live SPOF.** Architecture
   §19 gap #14 called it out. The design lists it in §13 risks and
   pushes it to P2. For a system whose entire audio path depends on
   this one file, that's wrong prioritization. It's a two-line hash
   check.
5. **No plan for the reviews/ audit trail.** `data/reviews/YYYY-MM-DD/`
   is currently in git and grows every run. The design's §8.2 lists
   new artefacts under `data/` but never says whether `data/reviews/`
   stays in git after the R2 migration. If it does, the repo growth
   problem is only half-solved.
6. **Gemini `response_schema` reliability on flash-lite is a listed
   unknown (§13) but has no fallback plan beyond "reparse via json.loads."**
   That's not a fallback, that's a hope. If schema-mode fails at 5%
   rate on flash-lite, the pipeline is now flaky on the P0 refactor
   that saves $2/mo.

---

## 5. Recommended sequence changes

Current order: Observability → LLM refactor → Audio → Storage → Model
upgrade → Batching/IPA.

Two problems with this. First, observability is being built to gate
things the golden set doesn't yet have baselines for (red team caught
this; the "everything in soft-fail for two weeks" band-aid means the
gates aren't actually gates during the entire migration). Second, the
R2 migration is the highest-leverage change in the doc and it's in
Phase 4.

**Recommended order:**

1. **Storage first (current Phase 4).** R2 migration + `.gitignore`
   for MP3s. Do **not** run `git filter-repo` yet. Stop the bleeding;
   fix the past later or never. Bounded growth from tomorrow.
2. **Audio quality (current Phase 3).** Voice sweep + punctuation
   preservation. Free, high-leverage, no LLM changes.
3. **LLM refactor (current Phase 2), Merge A only.** Skip Merge B split
   theater. Keep sanity separate.
4. **Observability (current Phase 1), scoped down.** Health dashboard
   (git-ignored) + WER history (monthly-rotated). Drop drift as a hard
   gate; keep it as a printed number in the dashboard. Golden set at
   30 rows is a smoke test — print pass/fail, don't exit non-zero.
5. **Reassess §4.3 model upgrade.** Only ship if §2 + §3 didn't close
   the audio-quality complaint.
6. **Git-history purge — only if the 588 MB is causing real pain.** For
   a single-user repo, 600 MB is annoying, not broken. Once R2 is
   serving and `.gitignore` is in place, growth stops. The purge saves
   ~550 MB of clone time on a repo the owner clones roughly never.

---

## 6. Refuse-to-sign items until fixed

A Principal SDE would not sign off on the following as written:

1. **§6.2 step 8 (git filter-repo).** Not because the procedure is
   wrong — because the *justification* is missing. For a single-user
   repo where MP3 growth is stopped by `.gitignore`, the purge is a
   destructive operation with no user-visible benefit. Either delete
   it from this design or add a paragraph explaining what breaks if
   you *don't* run it. As currently written, "it's one-way" is buried
   in a table row and the risk section, and the phase plan puts it in
   the critical path.
2. **§4.2 LLMProvider with three provider stubs, none testable end-to-end
   against a real API in CI.** Ship it as Gemini-only with an
   interface that admits future providers, or don't ship the abstraction
   at all. Do not commit `ClaudeProvider` and `OpenAIProvider` classes
   that no test exercises — that's dead code the next reader has to
   reason about.
3. **§7.1 drift `sys.exit(2)` on IQR breach.** Cannot ship a hard-fail
   gate on a metric that has known false-alarm modes the doc itself
   documents (source churn, weekend variance). Either soften to
   warn-only permanently, or move to a distributional statistic.
4. **Six-secret expansion in §8.3 with no rotation plan.** Add
   `docs/RUNBOOK.md` §Secrets with rotation cadence + revocation
   procedure before adding the secrets. This is 30 minutes of writing;
   there is no excuse to defer.

Everything else — the P2 deferrals, the mixed-voice period, the
markdown dashboard aesthetics, the 55%→30% call-reduction correction
— is fine. The design is materially stronger after the red/blue pass.
It's just still trying to do more work than a one-user product needs.
Ship the free wins (§5.1, §5.2, §6.1 without the purge, health
dashboard). Defer the paid ones (§4.3, three-provider abstraction).
Delete the theatrical ones (§4.1 Merge B split-A/B, §7.1 hard-fail
drift).
