# Briefing — Architecture Overview (for external critique)

> A personal, editorially-filtered audio news + long-form-tech briefing.
> Live at **briefing-psi-ten.vercel.app**. Source at
> **/Users/rahul5111/Desktop/newsbriefing** (git repo). Single-user product,
> owner reads/listens 1–3× daily.
>
> This document exists to be pasted into ChatGPT (or any external reviewer)
> for **critique and optimisation suggestions**. It is exhaustive on purpose.
> A "known gaps" section at the bottom lists the parts we already suspect
> are weak.

---

## 1. Product intent & operating constraints

**Goal.** For the owner (a tech-industry PM/engineer, India-based), produce
a curated audio + reader briefing 3×/day that respects:

- **Editorial bar.** No feel-good filler, no ceremonial coverage, no
  celebrity gossip, no listicles, no "police register FIR" micro-crime, no
  price-tick noise, no MoU / aspirational-target announcements. Bar is
  *higher* than GKToday's daily current-affairs standard.
- **Taxonomy (locked).** 8 categories: `AI`, `TECH`, `SCIENCE`, `SPORTS`,
  `US`, `INDIA`, `WORLD`, `BUSINESS`. Sub-taxonomy per PLAN.md.
- **Audio.** Neural TTS, news-anchor style. Voice `am_liam` for
  general news, `am_michael` for tech, `bm_george` for science.
  Playback rate 1.08×. No whispering. No mispronounced acronyms. Explicit
  paragraph pauses.
- **UI.** Editorial print aesthetic — single accent (vermilion), light
  theme only, no dark mode, no AI-slop chrome.
- **Cadence.** 3 crons/day (news), weekly (blogs). 7-day retention for
  news, 30-day retention per blog entry.
- **Autonomy.** Owner grants full permission to commit + deploy at every
  stable point; minimal interruptions.

**Non-goals.** Multi-user auth, social sharing, comments, personalisation
knobs beyond the fixed 8-cat taxonomy, real-time (< hourly) freshness.

---

## 2. High-level topology

```
                ┌────────────────────────────────────────────────────┐
                │        GitHub Actions cron  0 12,19,2 * * *        │
                │  (12:00 / 19:00 / 02:00 UTC — 3× daily)            │
                └───────────────────────┬────────────────────────────┘
                                        │
                                        ▼
    ┌────────────────────────────────────────────────────────────┐
    │                  python -m pipeline.run                    │
    │                                                            │
    │  1. fetch.py    — RSS / HN / Reddit / GNews / TLDR         │
    │  2. extract.py  — trafilatura article body + og:image      │
    │  3. dedup.py    — MiniLM cosine ≥0.82 (3-day window)       │
    │  4. significance.py — v2 filter (ACCEPT/REJECT/tighter)    │
    │  5. categorize.py — Gemini → 8-cat + sub                   │
    │  6. geolocate.py — Gemini → lat/lng anchor (optional)      │
    │  7. refine.py   — 6-layer Gemini rewrite (spoken)          │
    │  8. normalize.py — deterministic pronunciation pass        │
    │  9. tts.py      — Kokoro-ONNX synth per-chunk, MP3 out     │
    │ 10. audio_validate.py — Whisper tiny.en round-trip → WER   │
    │ 11. manifest.py — write feed.json                          │
    │                                                            │
    └───────────────────────┬────────────────────────────────────┘
                            │
                            ▼
        ┌────────────────────────────────────────┐
        │  git commit site/public/data data/*    │
        │  vercel pull / build / deploy --prod   │
        └────────────────────────────────────────┘

    (Blogs run on a manual/weekly trigger — same rails, separate manifest.)
```

Everything runs in a single Python 3.12 venv on the runner. No queues,
no workers, no DB. The manifests (`feed.json`, `blogs.json`) are the
source of truth and are served as static JSON from `site/public/data`.

---

## 3. Sources

### 3.1 News (`pipeline/sources.yaml`) — 90 enabled entries

Structured by 8-cat taxonomy. Feed types:

- **RSS (primary)** — Verge, Ars, BBC, Reuters, Al Jazeera, ScienceDaily,
  ESPN Cricket, Moneycontrol, Business Standard, etc.
- **Hacker News** — Algolia API, front page + `show_hn`.
- **TLDR variants** — tech, ai, webdev, infosec, design.
- **Google News proxies** — for outlets without stable RSS (Reuters syndication,
  WSJ, Bloomberg, The Wire, and India-desk stringers).
- **arXiv** — `cs.LG` + `cs.CL` only, 336h lookback.
- **Reddit** — schema present but currently **disabled** (OAuth pending).
- **Gmail newsletters** — schema present but currently **disabled**
  (OAuth read-only + sender allowlist pending).

Tier structure: **A** (wire, model labs, primary source), **B** (Verge,
TechCrunch, TLDR), **C** (HN, Reddit, community). Tier informs the
significance filter's downstream tolerance.

Lookback: 168h default; 48h for GNews proxies; 336h for arXiv/Anthropic.

### 3.2 Blogs (`pipeline/blogs.yaml`) — 20 sources

Individual voices: Martin Fowler, Gergely Orosz (Pragmatic Engineer),
Will Larson, Simon Willison, Lilian Weng (Lil'Log), Andrej Karpathy,
Mark Seemann (Ploeh), etc.

Company blogs: Netflix Tech, Cloudflare, Uber Eng, HighScalability.

AI research: DeepMind, Anthropic, OpenAI research (where distinct from
product blog).

Per-source `max_items` (usually 4–6), `topics` tags for retrieval later.

---

## 4. Fetch → Extract

- **`pipeline/fetch.py`** — orchestrator. Returns a list of
  `Candidate` dataclasses (title, url, text_from_rss, author, score,
  created_at_ts, hn_permalink). No caching; every run is fresh. Reddit
  path skipped. TLDR has a custom scraper.
- **`pipeline/extract.py`** — full article body via `trafilatura`. Skips
  YouTube/Vimeo/Twitter/PDF/MP4. Min body 120 words. 15s timeout.
  Returns text + og-image / twitter-image URL.

---

## 5. Filtering & de-duplication

### 5.1 `pipeline/significance.py`

**v1 (legacy, kept for tests):** `score_batch()` → categorical label
`{IMPORTANT|INTERESTING|ORDINARY|TRIVIAL|PROMOTIONAL}`.

**v2 (current, strict):** `score_v2_batch()` → `SignificanceV2` object.

- `score` ∈ [0.0, 1.0]
- `band`: `accept` (≥0.65) / `borderline` (0.35–0.65) / `reject` (≤0.15)
- `accept_hits` **A1–A10** — required signals (named entity + action, second-
  order consequence, state/national scope, primary source, sports/sci-tech
  criteria, reducibility to a <140 char headline, etc.).
- `reject_hits` **R1–R14** — hard-reject filters. Examples:
  - R1 ceremonial (Ganesh greetings, festival wishes)
  - R2 personal crime / sub-state incident (road rage, local altercation)
  - R3 celebrity gossip
  - R4 feel-good / uplift filler
  - R5 corporate PR / product-announcement without new capability
  - R6 listicle
  - R11 rumor / "reportedly considering"
  - R12 sub-state coverage (city-level administrative)
  - R14 sub-Padma / sub-national awards
- `tighter_penalties` **T1–T3** — post-accept downgrades:
  - T1 actionability (–0.2 if no reader action or consequence)
  - T2 novelty (–0.2 for routine repeats of the same beat)
  - T3 substance-over-signalling (–0.3 for MoUs, targets, aspirations)

`write_rejection_log()` appends every reject to
`data/rejections/YYYY-MM-DD.jsonl` with `{run_ts, id, title, url, band,
reason, hits}` for human audit and false-negative review.

### 5.2 `pipeline/dedup.py`

- Encoder: `sentence-transformers/all-MiniLM-L6-v2`.
- Cosine similarity ≥ **0.82** = duplicate.
- Compares candidates against (a) the last 3 days of published stories
  and (b) each other (in-batch first).
- Duplicate hits are logged to `data/duplicates/YYYY-MM-DD.jsonl` with
  `{new_index, new_title, matched_title, matched_kind: 'published'|'new', sim}`.
- Roadmap PLAN C4: **cross-source enrichment** — when a Tier-A source
  publishes the same story as an already-ingested Tier-B, we don't
  drop; we re-extract from Tier-A, re-refine, re-TTS, and append the
  new source to `sources[]`.

---

## 6. Categorization & geolocation

- **`pipeline/categorize.py`** — Gemini batch call, temperature 0.0, with
  the 8-cat + sub taxonomy in the prompt.
- Tie-break priority: **Science > AI > Sports > Tech > Business > US >
  India > World**. India/US preferred over World for domestic stories
  (fixes the "everything → WORLD" leak we saw earlier).
- Output: `{"main": "INDIA", "sub": "Policy & Governance"}`.
  Back-compat shim writes both `main`/`sub` and `category`/`subcategory`
  so the frontend can transition gradually.
- **`pipeline/geolocate.py`** — optional lat/lng anchor via Gemini.
  Priority: headline location > HQ of named company > product maker's HQ.
  Returns `null` if placeless (many software stories). Used by the
  globe visualisation on the front page.

---

## 7. Refine (6-layer LLM pipeline)

**`pipeline/refine.py`**, 546 lines. Uses `config.GEMINI_MODEL` (default
`gemini-3.5-flash-lite`).

| Layer | Name | Purpose |
| ----- | ---- | ------- |
| 1 | DRAFT | 150–360-word summary sized by article complexity. Facts, numbers, names, dates. One quote if strong. Zero editorialising. |
| 2a | WHY_MATTERS | Infer a single 12–28 word stakes line. Returns `"NONE"` on listicles/fluff (that flags the story as `thin` and demotes). |
| 2b | FACT_VERIFY | Regex-check numbers + proper nouns against the source. Any mismatch → re-draft. |
| 3 | AUDIO_REWRITE | Rewrite for spoken delivery. Numbers/currency/acronyms are spelled out inline. Short sentences (12–20 words). No dashes, parens, semicolons. Attribution mentioned once in sentence 2–3. Stakes line woven into paragraph 2, not appended. |
| 4 | PRONUNCIATION_NORM | Deterministic regex pass (see §8.1). Also extracts key-point set + measures coverage %. |
| 5 | SANITY_CHECK | Final LLM read-aloud check for TTS-tripping issues (unspelled acronyms, embedded lists, dangling clauses). |
| 6 | WRITE_REVIEW | Persist every stage to `data/reviews/{YYYY-MM-DD}/{story_id}.txt` for human review. |

Output `Refined` dataclass: `text` (TTS input), `word_count`,
`passes_used`, `sanity_notes`, `key_points`, `coverage_pct`,
`missing_points`, `stakes`, `thin: bool`.

Config knobs: `WORDS_MIN=150`, `WORDS_MAX=360`,
`COVERAGE_THRESHOLD=0.85` (must-include facts).

---

## 8. Audio

### 8.1 `pipeline/normalize.py` — deterministic pronunciation pass

Runs *after* the LLM has already been asked to spell out numbers/acronyms.
Acts as a safety net for anything the LLM missed.

- **PRONUNCIATION_MAP**: ~240 regex → phonetic rules, longest-first. Includes:
  - Indian names, festivals (`Ganesh Chaturthi`), Sanskrit terms
  - German/Austrian/Chinese place names
  - F1 drivers (`Verstappen`, `Leclerc`)
  - Tech: `Kubernetes → Koo-buh-NET-eez`, `Postgres`, `LangChain`,
    `Cassandra`, `Cloudflare`, `agentic → uh-JENT-ick`, ~60+ entries.
- **SPELL_OUT**: 60+ acronyms letter-spaced (`API → A. P. I.`, `NBA`,
  `RBI`, `GST`, `GPT`, `BERT`, `CLIP`, `RLHF`, `DPO`, `NLP`, `NER`,
  `OCR`, `ASR`, …).
- **Numbers**: `num2words`. Years → "twenty twenty-six". Versions →
  "three point eight". Currency → "forty million dollars". Ordinals,
  ranges, times (`3:45pm` → "three forty-five pee em").
- **Symbols**: `&` → "and", `%` → "percent", `@` → "at", etc.
- **Abbrs**: `e.g.` → "for example", `i.e.` → "that is", `U.S.` → "US".

### 8.2 `pipeline/tts.py` — Kokoro-ONNX synth

- Engine: **`kokoro-onnx` v1.0** (local ONNX model, no network call).
- Voice-by-category:
  - AI / TECH / BUSINESS → `am_michael` (crisp, energetic)
  - SCIENCE → `bm_george` (British, informative)
  - SPORTS / US / INDIA / WORLD → `am_liam` (broadcaster gravitas)
- **Speed**: 1.08× (prevents whisper-iness the owner flagged in the
  am_liam default).
- **Chunking**: split on sentence, re-merge if a split lands mid-acronym,
  break long sentences (>280 chars) at commas/conjunctions (~220 target).
- **Silence structure**: 0.15s pre-roll, 0.32s sentence gap, 0.60s
  paragraph gap (double-newline), 0.35s tail.
- **Output**: MP3, plus `stats` dict (`chunks_synthed`, `duration_s`,
  `sample_rate`, `voice`).

### 8.3 `pipeline/audio_validate.py` — Whisper round-trip

Prevents burning TTS credits on garbage:

- Transcribes the produced MP3 back to text with `faster-whisper tiny.en`.
- Runs **WER** + **CER** via Levenshtein against the input.
- `_normalize_for_diff()` applies `normalize.normalize()` to both sides
  and collapses letter-spaced acronyms (`"k l two"` → `"kltwo"`) so
  a Whisper miss of "K.L. two" doesn't false-alarm.
- Verdict: `good` (<0.10) / `acceptable` (<0.20) / `poor` (≥0.20).
- Also: 20 ms window silence analysis, gap classification. Flags if
  sentence gaps < 3, any suspicious gap > 1.5 s, WPM outside 130–160.
- Failures re-queue via `repar_and_retts.py`.

---

## 9. Blog pipeline (separate rails)

**`pipeline/blogs_run.py`**. Same fetch → extract → refine → TTS shape,
different economics:

- Manifest: `data/blogs.json` (segregated from feed).
- Retention: 30 days per entry (owner wants a 1-month clock).
- **Two-summary output**:
  - `summary_short` — 100–160 w, card hook, no code, no padding.
  - `summary_long` — **600–1500 w**, variable by post complexity (short
    opinion 600–800, meaty architecture 900–1200, deep paper walk 1200–
    1500). Long summary is the TTS input.
- Category "TECH" for pronunciation dict routing.
- Flags: `--dry` (no TTS), `--limit N`.
- Incremental save after every successful entry so a mid-run kill
  doesn't cost the entries already synthesised.
- Audio path: `blogs-audio/{YYYY-MM}/{entry-id}-{slug}.mp3`.
- Currently manual trigger. Weekly cron pending.

---

## 10. Cron & CI/CD

`.github/workflows/pipeline.yml`:

- **Schedule**: `0 12,19,2 * * *` (12/19/02 UTC → matches morning/lunch/
  overnight in owner's TZ).
- **Steps**:
  1. `actions/checkout` + Python 3.12 + pip cache.
  2. Install `ffmpeg`, `libsndfile1`.
  3. Cache `.models` (Kokoro) and `~/.cache/huggingface` (MiniLM,
     Whisper tiny.en).
  4. `python -m pipeline.run` — full ingest.
  5. `python -m pipeline.retention` — 7-day prune.
  6. `git commit site/public/data data/reviews` if changed.
  7. If a commit happened: `vercel pull --prod && vercel build --prod &&
     vercel deploy --prebuilt --prod`.
- **Secrets**: `GEMINI_API_KEY`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`,
  `VERCEL_PROJECT_ID`.

Known operational pain: (a) the cron `git push` occasionally races with
local pushes and needs `--pull --rebase --autostash`; (b) `VERCEL_TOKEN`
has expired twice — no automatic rotation.

---

## 11. Frontend

Astro 5.1 + React 19 islands. No SSR-time API calls; JSON is read from
disk at build time and passed as props.

- **`site/src/pages/index.astro`** — reads `public/data/feed.json`,
  computes total minutes / unique-source count, renders
  `<Feed client:load stories={} cdnBase={} />`.
- **`site/src/pages/blogs.astro`** — reads `public/data/blogs.json`,
  renders `<Blogs client:load entries={} cdnBase={} />`.
- **Components**:
  - `Feed.tsx` (631 lines) — story grid, category strip, sub-strip pill
    with shared-element transition via `motion` `layoutId`, on-demand
    floating player, `NowPlayingWave`, editorial "N°01 / Today" lede.
  - `Blogs.tsx` (336 lines) — expandable cards, arc-clock showing
    days-left, listen button, "read the original ↗", topic chips.
  - `AbstractCover.tsx` — cover art fallback.
  - `Globe.tsx` — react-globe.gl + Three.js, powered by
    `location.lat/lng`.
- Motion: `motion/react` (successor to `framer-motion`).
- **CDN**: `PUBLIC_CDN_BASE` env var. When set, audio is fetched from
  a jsDelivr mirror of the same repo; otherwise `/data` (Vercel static).

---

## 12. Data model

### 12.1 News story

```jsonc
{
  "id": "sha1-shortened",
  "title": "...",
  "summary": "150–360 words, TTS-ready",
  "main": "INDIA",
  "sub": "Policy & Governance",
  "category": "INDIA",          // back-compat mirror
  "subcategory": "Policy & Governance",
  "sources": [                  // multi-source hydration (PLAN C4)
    {"name": "Reuters", "url": "...", "domain": "reuters.com", "added_at": "..."}
  ],
  "source": "Reuters",          // legacy single-source field
  "source_url": "...",
  "source_domain": "reuters.com",
  "source_permalink": "...",
  "author": "...",
  "published_at": "2026-09-14T08:23:00Z",
  "created_at_ts": 1234567890,
  "score": 0.72,
  "audio_path": "audio/2026-09-14/xyz.mp3",
  "audio_duration_s": 82.4,
  "audio_bytes": 1_234_567,
  "audio_verdict": "good",
  "tts_chunks": 5,
  "tts_voice": "am_liam",
  "word_count": 218,
  "estimated_duration_s": 78,
  "image_url": "https://...",
  "location": {"name": "New Delhi", "country": "India", "lat": 28.6, "lng": 77.2}
}
```

### 12.2 Blog entry

```jsonc
{
  "id": "blog-<source>-<hash>",
  "type": "blog",
  "title": "...",
  "author": "Martin Fowler",
  "source": "martin_fowler",
  "source_display": "Martin Fowler",
  "source_url": "https://martinfowler.com/...",
  "topics": ["architecture", "refactoring"],
  "published_at": "...", "expires_at": "... +30d",
  "reading_time_min": 12,
  "summary_short": "100–160w hook",
  "summary_long": "600–1500w spoken-audio reader",
  "long_word_count": 1020,
  "audio_path": "blogs-audio/2026-09/...",
  "audio_duration_s": 358.2,
  "tts_chunks": 21, "tts_voice": "am_michael",
  "image_url": "https://..."
}
```

---

## 13. Storage layout

- **`data/`** (git-tracked, not web-served):
  - `rejections/YYYY-MM-DD.jsonl` — audit log for filter tuning
  - `duplicates/YYYY-MM-DD.jsonl` — dedup hits
  - `reviews/YYYY-MM-DD/<story-id>.txt` — every refine layer, human-readable
  - `pruned_YYYY-MM-DD.json` — repruned stories on filter tightening
- **`site/public/data/`** (web-served, mirrored to Vercel):
  - `feed.json` — **~353 KB, 106 stories** (as of 2026-09-14)
  - `blogs.json` — **~67 KB, 12 entries**
  - `audio/YYYY-MM-DD/*.mp3` — **154 MB** total in working tree
  - `blogs-audio/YYYY-MM/*.mp3` — **21 MB**
  - `rss.xml`
- **`.git` — 588 MB** and growing. Audio binaries checked in on
  every cron tick; retention prunes the working tree but git history
  keeps every blob. This is the biggest known-debt item.
- **No DB, no object store.** Entire product is ~420 KB of JSON + a
  few hundred MB of audio committed to git and served static. Deliberate
  simplicity choice for a single-user app — but see §19 gap #1.

---

## 14. Design rationale (why each choice)

A reviewer should not propose alternatives we've already considered.
Rationale for the load-bearing decisions:

- **Static JSON + audio in git, no DB.** Product is single-user, single-
  writer (the cron), read-mostly. A DB would add ops surface for no
  correctness win. Git gives us free versioning, free rollback, free
  backup, and a review trail. We know this doesn't scale — see §17.
- **Astro over Next.js.** No user auth, no server-side data mutation,
  no per-request personalisation. Astro's "islands" model gives us
  React only where interactivity lives (Feed player, Blogs reader) and
  a static shell everywhere else. Build is 8 s, cold-load is fast.
- **Gemini over Claude/GPT for pipeline LLM.** Cost per token at
  our volume ($~ per day, see §16). Latency is fine because we run
  offline in cron. Not because Gemini is *better* — we would switch
  the moment quality regresses. No multi-provider abstraction today.
- **Kokoro-ONNX local over ElevenLabs / Play.ht / OpenAI TTS.**
  Zero API cost, no rate limit, no vendor lock, deterministic output
  for a given voice+text. Trade-off: quality is behind ElevenLabs on
  prosody, and we compensate with the deterministic `normalize.py`
  pass plus manual voice-per-category selection. Whisper round-trip
  validation catches the worst regressions.
- **Whisper `tiny.en` as validator.** Cheap enough to run on every
  synth. Bigger models would catch more errors but the WER floor of
  `tiny.en` (~5–7 % on clean speech) is *good enough* as a regression
  detector — we're not measuring absolute quality, we're catching
  "TTS spit out obviously wrong words."
- **6-layer refine.** Each layer exists because a single-shot
  Gemini prompt failed in a specific way: hallucinated numbers
  (→ FACT_VERIFY), buried the stakes (→ WHY_MATTERS), had em-dashes
  that Kokoro read as pauses (→ AUDIO_REWRITE), or unspelled
  acronyms slipped through (→ PRONUNCIATION_NORM + SANITY_CHECK).
  It's not elegance — it's calcified bug fixes.
- **8-cat taxonomy, locked.** Owner-preferred set. `INDIA` and `US`
  are top-level because owner cares about both and Reuters-style
  "WORLD" was hiding India/US stories. `AI` split from `TECH`
  because AI volume is high enough to drown out the rest of tech.
- **Deterministic pronunciation dict + num2words.** Placed *after*
  the LLM has been asked to spell out numbers/acronyms. Safety net,
  not primary strategy. Ordered longest-first so `Kubernetes` beats
  a hypothetical `Kub`. Regex-based, no phoneme system yet.
- **Cron 3×/day at 12/19/02 UTC.** Aligns with owner's morning /
  lunch / late-night reading pattern in IST.
- **RSS + Google News proxy over paid news APIs.** Cheap, zero
  auth surface. Trade-off: extraction reliability varies, and some
  outlets (WSJ, Bloomberg) hide behind paywalls that trafilatura
  can't cross. We accept partial content and rely on multi-source
  hydration to fill gaps.

---

## 15. Prompt library (excerpts)

Full text lives in `pipeline/refine.py` and `pipeline/blogs_run.py`;
these are the load-bearing prompts a reviewer would want to critique.

### 15.1 DRAFT (refine layer 1)

> "Summarise this news article in 150–360 words. Length is chosen by
> the article's real information density — a two-paragraph brief is
> 150–180; a wire-service report with numbers, actors, and consequences
> is 250–360. Do not pad.
>
> Include: the concrete event (who did what where when), the numbers /
> names / dates that would be lost if omitted, one quote if the quote
> is strong, and the 'why it matters' angle **only if the source
> states it**. Do not editorialise; do not speculate; do not invent
> figures; do not use 'reportedly' unless the source itself does."

### 15.2 WHY_MATTERS (refine layer 2a)

> "In 12–28 words, state the stakes of this story for a reader who
> is not already following the beat. If the story has no stakes
> beyond 'this happened' (celebrity gossip, ceremonial coverage,
> local incident, listicle, feel-good), return the literal string
> `NONE`. Do not soften. Do not editorialise."

### 15.3 AUDIO_REWRITE (refine layer 3)

> "Rewrite as spoken audio for a news-anchor voice.
>
> - Spell out every number, currency, date, percent, port, code:
>   `$40M` → 'forty million dollars'; `2026` → 'twenty twenty-six';
>   `HTTPS` → 'H. T. T. P. S.'
> - Sentences 12–20 words. No dashes, parens, semicolons, colons —
>   rephrase around them.
> - Attribution inline, mentioned once in sentence 2 or 3.
> - Weave the stakes line into paragraph 2, not appended.
> - No throat-clearing ('In a recent development…'). Start with the fact."

### 15.4 Blog SHORT (100–160 w card hook)

> "Summarise this technical blog post as a 100–160 word hook
> paragraph for a reader-card. What the post is about (one sentence),
> the key argument or finding, why a working software engineer would
> open it. No padding ('This post explores…'), no editorialising
> ('groundbreaking'), no code, no attribution."

### 15.5 Blog LONG (600–1500 w audio reader)

> "Rewrite as a spoken-audio reader briefing for a senior engineer /
> PM. Length 600–1500 w, chosen by the post's real complexity: a
> short opinion post is 600–800, a meaty architecture post 900–1200,
> a deep paper walk-through 1200–1500. Do not pad, do not truncate.
> Include the problem, the design walked step by step, specific
> numbers / product names / algorithms spelled cleanly, the trade-offs
> the author names, and the conclusion. Code snippets described in
> prose ('the function takes a request handler and returns a
> middleware factory'), never quoted literally. Name the author once
> in the first two sentences."

**Design intent:** each prompt names its failure modes ("do NOT pad",
"do NOT editorialise") because empirically Gemini regresses to
generic AI-slop language without those guardrails. If a reviewer sees
a cleaner way to express the same intent, that's high-value feedback.

---

## 16. Empirical volumes & rough costs

| Metric | Current value | Notes |
|---|---|---|
| Stories in feed | **106** | after significance_v2 (was ~400 pre-v2) |
| Blog entries live | **12** | 30-day rolling window |
| feed.json size | 353 KB | serialized JSON |
| blogs.json size | 67 KB | ~5.5 KB per entry (long summary drives it) |
| Audio bytes (news) | 154 MB | ~1 min per story, ~1.5 MB each |
| Audio bytes (blogs) | 21 MB | 3–8 min per blog, variable |
| .git size | 588 MB | audio history — see §19 gap #1 |
| Cron frequency | 3×/day | 12/19/02 UTC |
| Gemini calls per run | ~600–1000 | 5–6 per story × ~150 candidates pre-filter |
| Whisper calls per run | = story count | ~30–50 |
| Full-run wall-clock | ~8–12 min | dominated by TTS + Whisper |

**Cost envelope (approx, based on gemini-3.5-flash-lite pricing):**

- Gemini spend: single-digit USD / month at current volume.
- Vercel: static hosting + edge bandwidth, free tier so far.
- Compute: GitHub Actions free minutes (public repo).
- **Total run-rate: < $10/month.** This informs the "don't over-
  engineer for cost" stance — we are nowhere near a cost cliff.

---

## 17. Observability, testing, security

### Observability (what we log, what we don't)

- **We DO log:**
  - Every rejected story → `data/rejections/YYYY-MM-DD.jsonl`.
  - Every dedup hit → `data/duplicates/YYYY-MM-DD.jsonl`.
  - Every refine layer's output → `data/reviews/YYYY-MM-DD/<id>.txt`.
  - Whisper WER + audio flags → written back onto the story record
    as `audio_verdict`.
- **We DO NOT have:**
  - Any metric aggregation (no Grafana, no Datadog).
  - Any alerting (silent failures pass unnoticed until next-day check).
  - Any dashboard for filter drift, Gemini spend, or cron success rate.
  - Any distribution-of-scores plot for `significance_v2`.
  - Any user analytics (single-user product, so mostly OK).

### Testing surface

- `pipeline/mock_test.py` — end-to-end pipeline with a fixed
  candidate set, no network. Used for regression on refine + normalize.
- `pipeline/test_one.py` — single-story integration test used when
  hand-tuning a prompt or filter rule.
- **No unit tests.** No CI test job (workflow only runs cron).
- **No golden-file diffing** for refine output.

### Security posture

- No user auth, no user data. Only owner reads the site.
- No PII stored; only public-web article content.
- Secrets in GHA: `GEMINI_API_KEY`, `VERCEL_TOKEN`,
  `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`. No rotation policy.
- Gmail source disabled pending OAuth read-only + sender allowlist
  (owner mandate: personal inbox must not leak).
- `.env` never committed; `pipeline/config.py` reads from env vars.
- Audio + JSON are public artifacts — no leakage concern.

---

## 18. Roadmap (distilled from PLAN.md)

Committed but not yet shipped. Ordered by priority the owner has signalled:

1. **Audio quality polish** — per-category pronunciation adapters
   (Track B.2), phoneme fallback via `phonemizer` / `espeak-ng`
   (Track B.3), automated Whisper audit sweep with an
   `unresolved.jsonl` (Track B.4).
2. **Blog cron** — currently manual weekly; wire up a GHA cron.
3. **Cross-source enrichment (PLAN C4)** — when Tier-A publishes
   the same story as Tier-B, hydrate and append instead of drop.
4. **arXiv ranker** — only surface a paper when a Tier-A desk has
   already cited it.
5. **Uplift/tone facet chip** — needs a `tone` field on stories.
6. **Google News as first-class source** (owner asked; currently
   used only for the RSS-less proxies).
7. **VERCEL_TOKEN rotation policy** — has expired twice.
8. **GHA cron `git pull --rebase --autostash`** — reduces the
   local-vs-cron push race.
9. **Move audio to R2/S3 with signed URLs** — reduces git weight.
   Not committed yet, awaiting critique.

---

## 19. Known gaps & open questions (for reviewer)

We already suspect the following. **Any critique that goes deeper than
this list is genuinely useful.**

1. **Committing binaries to git.** MP3s are checked in; the repo will
   grow unboundedly. Retention prunes JSON but git history keeps
   the blobs. Should we move audio to R2 / S3 with signed URLs?
2. **No queue / no idempotency.** Cron is at-most-once. If the runner
   dies mid-refine, that batch is retried whole on next tick — no
   fine-grained resume. Blog pipeline has an incremental save
   workaround; news pipeline does not.
3. **Whisper validation is post-hoc.** WER is checked *after* TTS
   burns budget. We could pre-validate normalize→phonemize output
   without invoking Kokoro.
4. **Gemini as sole LLM.** Every filter/rewrite/verify call is
   Gemini. No fallback provider, no consensus check. Fact-verify is
   a regex not a semantic diff.
5. **Categorization is one-shot.** No self-critique; miscategorised
   stories only surface via manual audit.
6. **`significance_v2` is heuristic.** The A/R hit sets were tuned
   against GKToday plus owner rejections. No labelled eval set, no
   drift monitoring.
7. **Blog freshness.** Weekly cadence is manual. No automated poll.
8. **No preview environment.** Every commit goes to prod because
   there's no staging manifest.
9. **Reddit + Gmail sources are dark.** Schemas exist, ingestion is
   off. Gmail requires OAuth read-only + sender allowlist before
   we turn it on.
10. **arXiv ranker is naive.** All accepted arXiv papers surface;
    no citation-count or venue signal. Roadmap: only surface when
    a Tier-A desk has already cited.
11. **Audio pronunciation adapters per-category (Track B.2)** —
    parked. Currently one global dict; a science story with a
    biochem term and a sports story with a foreign player name
    share the same lookup table.
12. **Phoneme fallback** — for names not in the dict, we do not
    call `espeak-ng` / `phonemizer`. Long tail is uncovered.
13. **Costs unmodeled.** No dashboard for Gemini spend, Vercel
    bandwidth, or per-story dollar cost.
14. **Single point of failure: Kokoro model file.** Local ONNX,
    cached in Actions. If HF hosting changes, cron fails silently
    (audio missing but manifest still writes).
15. **No canary on filter changes.** Tightening `significance_v2`
    tomorrow could wipe the feed to zero and the cron would still
    commit + deploy an empty briefing.

**Questions we'd like ChatGPT to weigh in on, in priority order:**

1. **Refine pipeline shape.** Is the 6-layer refine over-engineered?
   Could a single well-structured Gemini prompt with function-calling
   + structured output do 80 % of the job at 20 % of the cost?
   What's the specific test we could run to know?
2. **Filter drift detection.** Cheapest reliable way to detect that
   `significance_v2` output distribution has materially shifted?
   (Ideally something that runs inside the same cron and either
   commits an alert file or fails the build.)
3. **Fact-verify layer.** Currently a regex diff of numbers +
   proper nouns against source text. What's the smallest upgrade
   that catches semantic hallucinations without adding a second LLM
   round-trip per story?
4. **Prompt engineering.** Given the §15 excerpts, which prompt is
   most likely under-performing, and what specifically would you
   change? Rewrite one prompt as a concrete counter-proposal.
5. **Audio validation choice.** Is Whisper `tiny.en` round-trip the
   right validator, or would a text-only phonemizer round-trip catch
   90 % of issues at 10 % of the cost?
6. **Storage choice.** Committing MP3s to git — real problem now
   at 588 MB, or premature to move? If we should move, is R2 /
   Backblaze B2 / Cloudflare Images the right destination for a
   read-mostly, single-user, ~200 MB corpus?
7. **Categorization robustness.** Single Gemini call, no self-
   critique. Is a two-pass "propose + verify" worth the extra call?
   Or is the answer to add rule-based pre-filters that force certain
   categories deterministically (e.g. arXiv URL → SCIENCE)?
8. **Cron reliability.** GHA cron with occasional git-push races is
   fragile. Is there a simpler durability story than moving to a
   real queue?
9. **The static-JSON-in-git shape.** For a single-user product, is
   this shape genuinely correct, or is it hiding pain we haven't
   felt yet (e.g. once corpus > 1 GB, once we want previews)?

### What we've already ruled out (don't re-propose)

- Moving to a paid TTS (ElevenLabs / OpenAI / Play.ht) — cost + lock-in.
- Multi-user auth or personalisation — non-goal.
- Real-time / streaming ingestion — non-goal, hourly is enough.
- Next.js migration — Astro's static-first fits the read-mostly
  shape better; no server-side data mutation to justify Next.
- Dark mode — owner-rejected.
- LangChain / LlamaIndex / agent frameworks around the pipeline —
  adds abstraction without solving a real problem; pipeline is
  deterministic control flow.
- Vector DB for dedup — MiniLM in-process at N ~ 500 is fine; we
  do not have a similarity-search product surface.
- Kubernetes / serverless workers / queues — pipeline runs in
  under 15 min on a single GHA runner. Complexity budget better
  spent on quality.
- **Refactors that preserve behaviour** — the owner does not want
  cleanup for its own sake; changes must move a specific quality
  or reliability needle.

---

## Appendix A — File map

```
pipeline/
  __init__.py
  fetch.py               50   RSS/HN/TLDR/GNews fetch orchestrator
  extract.py             81   trafilatura article extraction
  dedup.py              120   MiniLM cosine dedup, 0.82 threshold
  significance.py       302   v1 + v2 scorers, rejection log
  categorize.py         260   8-cat + sub via Gemini
  geolocate.py          100   lat/lng anchor via Gemini
  refine.py             546   6-layer Gemini rewrite
  key_points.py         141   must-include fact extraction
  normalize.py          514   pronunciation dict + num2words
  tts.py                223   Kokoro-ONNX synth
  audio_validate.py     247   Whisper tiny.en round-trip
  manifest.py            39   feed.json writer
  retention.py           29   7-day audio+manifest prune
  reprune.py            117   re-apply significance_v2 across manifest
  reclassify.py         113   re-run categorize across manifest
  revalidate.py          41   re-run audio_validate across manifest
  repar_and_retts.py    124   re-refine + re-TTS the failing stories
  run.py                389   top-level orchestrator
  blogs_run.py          353   weekly blog pipeline
  audit_significance_v2.py    filter audit tool
  sources.yaml               90 news feeds
  blogs.yaml                 20 blog feeds

.github/workflows/pipeline.yml    3× daily cron

site/
  src/pages/index.astro           news reader
  src/pages/blogs.astro           long-form reader
  src/components/Feed.tsx         631 lines — story grid + player
  src/components/Blogs.tsx        336 lines — blog grid + player
  src/components/AbstractCover.tsx
  src/components/Globe.tsx

data/                             audit trails, git-tracked
site/public/data/                 manifests + audio, web-served
docs/PLAN.md                      roadmap
docs/persona-and-audit-plan.md    Priya Menon audit spec
docs/tracks-abc-plan.md           Tracks A/B/C execution plan
docs/sources-for-review.md        110-source list for validation
docs/architecture-overview.md     ← this file
```
