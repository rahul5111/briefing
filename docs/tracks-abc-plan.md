# Tracks A / B / C — sequential execution plan

Received 2026-09-14. User wants strict quality filtering, better audio
pronunciation, and a new blogs section — sequential (not parallel) so
each ships properly.

Persona doc `docs/persona-and-audit-plan.md` is still authoritative. This
doc adds the new constraints from the 2026-09-14 message on top.

---

## Track A — Strict significance filter (BLOCKING; ship first)

**Problem.** User's screenshots show "Jharkhand Governor greets people on
Ganesh Chaturthi" and "Gurugram road rage caught on camera" surfaced in
INDIA as featured stories. Both are trivial / tabloid. He wants only
nation-level, important, needed-to-know news. GKToday.in (UPSC-exam prep
curator) is one reference standard; our bar should be strictly higher.

**Design constraints.**
- Applies across every main category, not just INDIA.
- No hard blocklist — categorical rules only. Blocklists rot.
- Filter runs at the `significance` layer, before refine and TTS spend.
- Track the reason for every drop so we can audit false negatives.

**Design.**
1. Sub-agent extracts GKToday's implicit editorial rules from their
   category pages. Codifies as ACCEPT + REJECT criteria.
2. New `pipeline/significance.py::score_v2` uses a Gemini prompt built
   from those rules. Returns one of NATIONAL / PROFESSIONAL / INTERESTING
   / TRIVIAL / TABLOID / CEREMONIAL / PROMOTIONAL, with a one-line reason.
3. Only NATIONAL + PROFESSIONAL + INTERESTING pass. TRIVIAL / TABLOID /
   CEREMONIAL / PROMOTIONAL are rejected. Reasons logged to
   `data/rejections/YYYY-MM-DD.jsonl` for audit.
4. Persona-fit rider: even INTERESTING-verdicts get down-weighted if
   they match Priya's ignore-list (NFL/NBA/MLB, celebrity, shopping
   listicles). Persona-fit tag added at classify time already.

**Validation.**
- Manually re-score the 400-story current manifest against the new
  filter. Expected: 40-60% rejected. Audit the surviving 40-60%: would
  Priya close any of them? Iterate rules.
- A/B: same day's raw candidate pool → old filter vs. new filter →
  count of stories that pass. New should be tighter but not zero.
- Re-run against a specific bad-case set: the two screenshots above +
  10 other examples of noise.

**Challenge.**
- What if we drop everything? Answer: sub-agent will estimate drop rate
  in advance. If >75%, loosen INTERESTING criteria to allow "regional
  policy with national precedent" back in.
- What if the LLM disagrees with GKToday? Answer: the prompt states our
  standard is HIGHER than GKToday's, and gives explicit examples of
  hard-drops. Sample deltas will be logged.
- What about breaking news that hasn't been "adjudicated" yet? Answer:
  ACCEPT criteria include "story is developing on multiple wires" as a
  fast-path.

**Ship.** New score_v2 wired into `run.py`. Rejections log to
`data/rejections/`. UI unchanged. Next cron produces a filtered manifest.

---

## Track B — Audio pronunciation upgrade

**Problem.** Kokoro is still mispronouncing tricky words. Current
PRONUNCIATION_MAP is hand-tuned and has good coverage for known cases
but doesn't scale to arbitrary tech jargon or foreign names.

**Design constraints.**
- Must stay on free tier / local CPU.
- Cannot switch away from Kokoro without user approval (their voice
  choice is locked; see feedback_voice memory).
- Should degrade gracefully — if a phoneme lookup fails, fall back to
  the current text.

**Design (staged; ship in order).**
1. **B.1 — Expand PRONUNCIATION_MAP for tech.** Whole-word entries for
   tech/AI jargon Kokoro trips on: Cloudflare, Kubernetes (KOO-buh-NET-eez),
   Postgres, Prisma, Kafka, Redis, MongoDB, Grafana, Prometheus, OAuth,
   OpenAPI, WebAssembly, LangChain, LangGraph, RAG (already), embeddings,
   fine-tune, quantise/quantize, hyperparameter, transformer,
   attention-head, sharding, sidecar, mesh, etc.
2. **B.2 — Per-category adapter maps.** A category can carry its own
   supplementary map. TECH gets the technical dict; INDIA carries the
   Indian-names dict; SPORTS carries player names by discipline.
   `normalize.normalize(text, main_category="TECH")` applies the base
   map + the category adapter.
3. **B.3 — Phoneme fallback via `phonemizer` (espeak-ng).** For any
   proper noun the LLM emits that isn't in the map, look it up in
   espeak's phoneme dict and emit an IPA-hinted pronunciation. Only for
   words flagged as "unknown proper noun" by the LLM.
4. **B.4 — Automated audit sweep.** After each cron, re-transcribe 5
   randomly sampled stories with Whisper, extract diff pairs where
   Whisper's word doesn't match input, add the top 10 unresolved
   mispronunciations to `data/audio/unresolved-YYYY-MM-DD.jsonl` for
   monthly manual PRONUNCIATION_MAP review.

**Validation.**
- Whisper WER on a fixed test-set (existing 8-cat sample). Target: WER
  drops from ~0.10 mean to ~0.05 mean across the sample.
- Manual spot-check on the specific words the persona audit flagged:
  Shri, Ganesh, Jharkhand, GPT-6, USB-C, Kubernetes, Kohli, Perplexity.
- MCP `chrome-devtools` playback of prod audio in a browser: not
  strictly needed if Whisper covers it.

**Challenge.**
- Does `phonemizer` actually improve Kokoro's output? Kokoro is a
  neural TTS with its own grapheme-to-phoneme. Providing IPA might
  confuse it, not help it. Test with a small sample first.
- If B.3 doesn't clearly win, ship only B.1 + B.2.

**Ship.** In order B.1 → B.2 → B.3 → B.4. Commit + Whisper audit after
each. Don't ship B.3 unless the WER improves.

---

## Track C — Blogs section (new pipeline + page)

**Problem.** User is a techie. Wants a curated /blogs page for
long-form engineering blogs (Pragmatic Engineer, Netflix Tech, Uber
Eng, Cloudflare, HighScalability, Ploeh, Fowler, Norvig, Will Larson,
etc.). These need:
- Variable summary length (no 1-2 min cap).
- Tech-aware TTS pronunciation.
- Summary shown on click; source link at bottom.
- Monthly rotation (each entry has a 1-month clock).

**Design constraints.**
- New schema entirely (not a "story" — it's a "blog entry").
- New page `/blogs` with grid layout matching the current editorial
  aesthetic.
- Manifest split: `feed.json` unchanged for news, `blogs.json` new.
- Pipeline run parallel-safe: `pipeline.blogs_run` runs weekly (not
  every 6h) since blog posts are slow-cadence.
- Retention 30 days (blogs get 1 month clock).

**Design.**
1. **C.1 — Blog source list.**
   Tier A curators (individuals):
   - Martin Fowler (`martinfowler.com/feed.atom`)
   - Peter Norvig (`norvig.com/`)
   - Will Larson (`lethain.com/feeds/`)
   - Gergely Orosz / Pragmatic Engineer (`newsletter.pragmaticengineer.com/feed`)
   - Jeff Atwood / Coding Horror (`blog.codinghorror.com/feed/`)
   - Hillel Wayne (`hillelwayne.com/index.xml`)
   - Ploeh (`blog.ploeh.dk/atom.xml`)
   - Uncle Bob (`blog.cleancoder.com/atom.xml`)

   Tier A company blogs:
   - Netflix Tech (`netflixtechblog.com/feed`)
   - Uber Engineering (`uber.com/blog/engineering/rss/`)
   - Cloudflare (`blog.cloudflare.com/rss/`)
   - High Scalability (`highscalability.com/rss/`)

   Verify each is live. Fall back to Google News proxy if RSS is down.

2. **C.2 — Blog entry schema.**
   ```json
   {
     "id": "blog-<slug>",
     "type": "blog",
     "title": "...",
     "author": "...",
     "source": "netflix_tech",
     "source_name": "Netflix Tech Blog",
     "source_url": "https://...",
     "published_at": "...",
     "expires_at": "<published + 30 days>",
     "topics": ["AI", "distributed-systems", "microservices"],
     "reading_time_min": 12,     // estimated from word count
     "summary_short": "150 words — the tl;dr for the card",
     "summary_long": "600-1500 words — the deep read + audio",
     "audio_path": "blog-audio/YYYY-MM/<id>.mp3",
     "audio_duration_s": 320.5,
     "image_url": "..."
   }
   ```

3. **C.3 — Refine prompts for blogs.**
   Two-summary output:
   - `summary_short` — 100-160 words, for the card, no attribution
     needed (source domain is separately visible).
   - `summary_long` — 600-1500 words, the click-through. Explains
     architecture, code snippets described in prose, trade-offs, why
     you'd read this. This is what gets TTS'd.

4. **C.4 — TTS with technical dictionary.**
   TECH pronunciation dict from Track B.2 is applied. If Track B.3 ships,
   fallback phoneme lookup covers arbitrary tech terms. Voice: bm_george
   or am_michael (informative feel).

5. **C.5 — /blogs page.**
   Grid of blog cards, source-colored kickers, reading-time chip, "1
   month clock" progress meter (shrinks from full → empty as the
   expires_at approaches). Click → full summary reader + audio player.
   Sort by source or by "freshest."

6. **C.6 — Monthly rotation.**
   `pipeline.blogs_prune` deletes entries where `expires_at < now`.
   Runs daily as a cheap cron job.

**Validation.**
- Ingest one week of blog RSS. Manually check summaries are technically
  accurate (a bad summary of a distributed-systems post is worse than
  no summary — user is a techie).
- TTS pronunciation on a technical blog end-to-end: does "Kubernetes",
  "Postgres", "OAuth 2.1", "GraphQL Federation" all read correctly?
- Playwright screenshot at 1440/1024/768/390.

**Challenge.**
- Long summaries might drift factually. Answer: coverage-gate at 90%
  (higher than the news 85%).
- Does the user actually want TTS on 600-1500 word technical summaries?
  He said yes ("summary that you prepare for each of the blog is the
  one that you will be using to convert into audio"). Confirmed.
- Are the individual blogs' RSS feeds all live? Sub-agent verifies.

**Ship.** In order C.1 (sources) → C.2 (schema) → C.3 (refine) →
C.4 (TTS) → C.5 (page) → C.6 (rotation). Each ships own commit +
deploy. C.5 is the big-visible one; C.6 can lag by a week.

---

## Execution order

1. Track A ships first (single day of work). Manifest quality improves
   immediately after next cron.
2. Track B ships next (2 stages: B.1+B.2 together, B.3 conditional).
3. Track C is the multi-day project. Sequenced C.1 → C.6.

At each track boundary I stop, run the audit, deploy, and report before
starting the next.

Silent mode: no chat until a track ships or an unblock is needed.
