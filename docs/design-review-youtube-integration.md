# Design Review — YouTube Current-Affairs Source Integration

Response to the specification in `log1.txt`. **Analysis and design only — no
code modified.** Follows the 26-item required output structure in §34 of the
brief. Every recommendation is classified **P0 / P1 / P2** and connected to
either the persona or a concrete design requirement from the brief.

The initial channels are:

- **Drishti IAS English** — `@DrishtiIASEnglish`
- **Unacademy IAS English** — `@UnacademyIASEnglish`

Both are added as **secondary explainer / curation** sources — not as primary
reporting. The purpose is to close the paywall gap on Indian current affairs
(especially where Hindu / Business Standard / Livemint articles are behind a
soft paywall) and to feed a coverage-audit loop that improves
`significance_v2` over time.

---

## 1. Current pipeline behavior relevant to this change

Cross-checked against `pipeline/fetch.py`, `pipeline/extract.py`,
`pipeline/dedup.py`, `pipeline/significance.py`, `pipeline/categorize.py`,
`pipeline/refine.py`, `pipeline/manifest.py`, `pipeline/run.py`,
`pipeline/sources.yaml`.

**Facts to build on:**

- **Fetch** is a source-type dispatcher (`rss` / `hn` / `reddit` / `tldr` /
  `gmail`). Adding `youtube` fits the existing pattern.
- **Extract** is `trafilatura` over HTML article bodies. Not applicable to
  YouTube — video needs a separate content-extraction path.
- **Dedup** is MiniLM cosine ≥ 0.82 against a 3-day window, drop-only today.
  The `2026-09-14` design review already proposed a two-stage event-aware
  cluster model (`event_id`, `event_update_type`,
  `data/clusters.json`). This YouTube design **plugs into that**, it does
  not re-invent it.
- **Significance** currently uses `score_v2_batch` with A1–A10 accepts,
  R1–R14 rejects, T1–T3 penalties. The `2026-09-14` review proposed
  replacing T1 (actionability) with an informational-significance vector
  and adding `persona_relevance`. This YouTube design assumes those changes
  are in flight and adds new signals (`source_role`, `retrospective_importance`).
- **Categorize** is a single Gemini batch call producing `{main, sub}` (soon
  also `topics`, `entities`, `regions`, `story_type`, `impact_scope`,
  `importance`). YouTube-derived event candidates enter the same
  categorization step — one code path, not a parallel one.
- **Refine** is 6 layers. YouTube-derived stories go through the *same*
  refine layers when they graduate to a published card.
- **Manifest** writes `feed.json`. Adding a `provenance` block per story is
  additive.
- **Run** is a linear orchestrator. Adding a YouTube stage before
  `fetch → extract → dedup → categorize → refine → tts` is the cleanest
  point of insertion, because YouTube events feed *candidates* into the
  same downstream pipeline.

**Constraint that shapes the design:** the pipeline currently runs 3×/day
inside a single GHA cron job, ~8–12 min end-to-end. YouTube video
analysis is expensive and slow. So the design must be **cheap-first** and
**budget-controlled**, with deep video analysis triggered only when needed
(brief §4).

---

## 2. Proposed YouTube source architecture

Six deterministic stages plus a provider abstraction. Fits inside the
existing linear cron.

```
   ┌──────────────────────────────────────────────────────────────────┐
   │  A. DISCOVERY                                                     │
   │  YT Data API v3 → channels.list → uploads playlist →              │
   │  playlistItems.list → videos.list (metadata only)                 │
   │  Persist: pipeline/state/youtube_seen.jsonl                       │
   └────────────┬─────────────────────────────────────────────────────┘
                │  new videos only
                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  B. METADATA CLASSIFICATION                                       │
   │  Cheap Gemini call (title + desc + duration + channel)            │
   │  → video_class ∈ {DAILY_CURRENT_AFFAIRS | WEEKLY | MONTHLY |      │
   │    SINGLE_TOPIC_EXPLAINER | EDITORIAL_ANALYSIS | ECONOMY_RECAP    │
   │    | SCIENCE_TECH_RECAP | POLITY_GOVERNANCE | INTERNATIONAL       │
   │    | SPORTS_CURRENT_AFFAIRS | SHORT | LIVE_STREAM |               │
   │    COURSE_PROMOTION | UNRELATED | UNKNOWN}                        │
   │  → language, likely_promotional_pct                               │
   │  Drop SHORT / LIVE_STREAM / COURSE_PROMOTION / UNRELATED here.    │
   └────────────┬─────────────────────────────────────────────────────┘
                │
                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  C. DESCRIPTION / CHAPTER PARSING                                 │
   │  Deterministic regex — extract chapter timestamps + labels        │
   │  from description. No LLM. Free.                                  │
   │  If chapters exist → produce chapter_topics[] and skip Stage D    │
   │  for videos whose chapters already resolve to N events.           │
   └────────────┬─────────────────────────────────────────────────────┘
                │
                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  D. EVENT PRE-MATCHING                                            │
   │  For each chapter_topic (or the whole video if no chapters):      │
   │    cheap Gemini call → does this match any recent Briefing        │
   │    story/cluster?                                                 │
   │  → outcome ∈ {EXISTING_EVENT_NEEDS_CONTEXT | NEW_POTENTIAL_EVENT  │
   │    | AMBIGUOUS | LOW_RELEVANCE | ALREADY_SUFFICIENTLY_COVERED}    │
   │  Only chapter_topics scoring above budget threshold pass to E.    │
   └────────────┬─────────────────────────────────────────────────────┘
                │
                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  E. SELECTIVE VIDEO UNDERSTANDING (Gemini video URL analysis)     │
   │  Only for: NEW_POTENTIAL_EVENT candidates that meet significance  │
   │  threshold, OR EXISTING_EVENT_NEEDS_CONTEXT where delta value     │
   │  looks high. Budget-gated (§16).                                  │
   │  Emits Event Candidate objects (schema §9).                       │
   └────────────┬─────────────────────────────────────────────────────┘
                │
                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  F. INTEGRATE                                                     │
   │  Two paths:                                                       │
   │  (1) EXISTING_EVENT + useful delta → append enrichment_deltas[]   │
   │      onto the existing story. No new card. §11.                   │
   │  (2) NEW candidate → feed the normal downstream pipeline as a     │
   │      pseudo-Candidate (categorize → significance → dedup → refine │
   │      → TTS), with source_role = SECONDARY_EXPLAINER + provenance. │
   │  Weekly/Monthly videos take an audit-only path (§13–15) that      │
   │  writes to data/audits/, not feed.json.                           │
   └──────────────────────────────────────────────────────────────────┘
```

**Key architectural choices:**

- **Discovery is separated from understanding.** Discovery is cheap and
  runs every cron. Understanding is expensive and runs selectively.
- **Chapter parsing pays for itself.** Many current-affairs channels
  include chapter timestamps; parsing those regex-cheaply avoids Gemini
  calls on whole videos.
- **Every event candidate goes through the same downstream refine + TTS.**
  We do not create a parallel "YouTube-refined" pipeline. That way,
  a Drishti-discovered story reads identically to a Reuters-discovered
  story in the final feed — only its provenance differs.
- **Weekly and Monthly videos never publish stories directly.** They
  produce audit records. This preserves the persona rule
  "UPSC_IMPORTANT != BRIEFING_IMPORTANT" (brief §13).

---

## 3. API / provider choices and why

| Layer | Choice | Rationale |
|---|---|---|
| **Video discovery** | YouTube Data API v3 (public) | Official, supported, quota-well-documented (10,000 units/day free tier). No scraping. Handles handle → channel_id → uploads playlist → videos.list cleanly. |
| **Auth** | API key (server-side), not OAuth | Public-channel discovery requires only an API key. OAuth is unnecessary (brief §32) and would drag in refresh-token management. |
| **Video understanding** | `VideoUnderstandingProvider` interface, current impl = Gemini video URL analysis | Brief §3 explicitly requires abstraction. Gemini can analyze a public YouTube URL directly; that's the current best path. |
| **Metadata classification** | Gemini `gemini-3.5-flash-lite` (same model as rest of pipeline) | Cheap, short prompt. No new model dependency. |
| **Chapter parsing** | Deterministic regex, no LLM | Chapters follow a stable format (`00:00 Label`, `HH:MM:SS Label`). Free. |
| **Not used** | yt-dlp, unofficial timed-text endpoints, caption-scraping libraries | Explicitly forbidden by brief §2. Would break intermittently and creates legal exposure. |
| **Not used** | Whisper on downloaded audio | Requires video download (ToS violation) and adds ~30 min compute per hour of video. |

**Why the provider abstraction matters:** if Google changes Gemini video URL
pricing/quotas (as it did to other Gemini features in the past year), we
swap the implementation without touching the pipeline. Candidate future
implementations: OpenAI GPT-4o with YouTube URL, Anthropic Claude with
YouTube URL, or a self-hosted transcript+summarize stack when yt-dlp is
authorized (per brief §2, only after separate approval).

**Interface (Python):**

```python
class VideoUnderstandingProvider(Protocol):
    def can_process(self, video_url: str, duration_s: int) -> bool: ...
    def analyze_video(self, video_url: str, hint: dict) -> VideoAnalysis: ...
    def extract_events(self, video_url: str, chapters: list[Chapter], hint: dict) -> list[EventCandidate]: ...
    def analyze_segment(self, video_url: str, start_s: int, end_s: int, hint: dict) -> SegmentAnalysis: ...
    def summarize_context(self, video_url: str, existing_story_id: str, chapter: Chapter) -> Optional[Enrichment]: ...
```

`hint` carries provenance + channel strengths + recent-corpus summary
(for pre-match). Provider returns structured objects; the pipeline never
sees provider-native shapes.

---

## 4. Channel configuration schema

New file: `pipeline/youtube_sources.yaml`. Declarative, matches the shape
already used in `sources.yaml` / `blogs.yaml`. Two seed entries:

```yaml
youtube_sources:

  - name: drishti_ias_english
    enabled: true
    handle: "@DrishtiIASEnglish"
    display_name: "Drishti IAS English"

    source_roles:
      - SECONDARY_EXPLAINER
      - CURATION_SOURCE

    strengths:
      india_policy: high
      governance: high
      international_relations: high
      economy: high
      science: medium
      technology: medium
      sports: low

    # Behaviour flags.
    process_daily: true          # daily current-affairs videos feed discovery+enrichment
    process_weekly: true         # weekly recaps feed coverage-audit
    process_monthly: true        # monthly recaps feed retrospective-significance

    # Filters.
    min_video_duration_s: 300    # skip Shorts and micro-clips
    max_video_duration_s: 5400   # cap at 90 min; longer videos are usually workshops
    max_age_hours: 48
    language: en                 # for the "English" variant channel
    exclude_video_types:
      - COURSE_PROMOTION
      - LIVE_STREAM
      - SHORT
    excluded_title_patterns:
      - "^Free Class"
      - "Batch Announcement"
      - "Live Doubt"

    # Cost controls (§16).
    max_new_videos_per_run: 6
    max_deep_analysis_per_run: 2
    default_confidence: 0.70     # baseline; per-event confidence can drop below

  - name: unacademy_ias_english
    enabled: true
    handle: "@UnacademyIASEnglish"
    display_name: "Unacademy IAS English"

    source_roles:
      - SECONDARY_EXPLAINER
      - CURATION_SOURCE

    strengths:
      india_policy: high
      law: high
      economy: high
      governance: high
      international_relations: high
      science: low
      technology: low

    process_daily: true
    process_weekly: true
    process_monthly: false      # Unacademy monthly recaps are exam-heavy; skip

    min_video_duration_s: 300
    max_video_duration_s: 5400
    max_age_hours: 48
    language: en
    exclude_video_types:
      - COURSE_PROMOTION
      - LIVE_STREAM
      - SHORT
    excluded_title_patterns:
      - "^Educator"
      - "Special Class"

    max_new_videos_per_run: 6
    max_deep_analysis_per_run: 2
    default_confidence: 0.65
```

New channels are added by appending an entry. No code change.

**Onboarding gate (P1):** brief §17 requires an evaluation phase before
production enablement. Recommended: new entries default to
`enabled: false, quality_gate: unverified`. A shadow run must produce an
audit for one week before flipping `enabled: true`.

---

## 5. New data-model fields

Additive. Legacy stories treated as if all new fields are absent /
default.

### 5.1 Story record — extensions to `feed.json` entries

```jsonc
{
  // Existing fields unchanged (id, title, summary, main, sub, sources[],
  //   audio_path, published_at, score, location, etc.).

  // Existing sources[] (already schema'd) is extended, not replaced:
  "sources": [
    {
      "name": "The Hindu",
      "url": "https://www.thehindu.com/...",
      "domain": "thehindu.com",
      "added_at": "...",
      "source_role": "INDEPENDENT_REPORTING",   // NEW
      "access_state": "PAYWALL_HEADLINE_ONLY"   // NEW: OK | PAYWALL_HEADLINE_ONLY | PAYWALL_METERED | EXTRACT_FAILED
    },
    {
      "name": "Drishti IAS English",
      "url": "https://www.youtube.com/watch?v=...",
      "domain": "youtube.com",
      "added_at": "...",
      "source_role": "SECONDARY_EXPLAINER",
      "access_state": "OK",
      "video_id": "...",                          // NEW
      "segment_start_s": 1110,                    // NEW
      "segment_end_s": 1515                       // NEW
    }
  ],

  // NEW: source_role summary for card display without walking sources[].
  "source_roles_present": ["INDEPENDENT_REPORTING", "SECONDARY_EXPLAINER"],

  // NEW: enrichment deltas kept for audit and Level-3 UI (design-review §5).
  "enrichment_deltas": [
    {
      "source_id": "drishti_ias_english",
      "video_id": "...",
      "video_url": "https://www.youtube.com/watch?v=...",
      "segment_start_s": 1110,
      "segment_end_s": 1515,
      "delta_type": "HISTORICAL_CONTEXT",       // CONTEXT | CONSEQUENCE | AFFECTED_GROUPS |
                                                //   IMPLEMENTATION_DETAIL | REDUNDANT | UNSUPPORTED
      "content": "Prior law was introduced in 2013…",
      "confidence": HIGH,                        // HIGH | MEDIUM | LOW
      "provenance": { ... }                      // full provenance block (§14)
    }
  ],

  // NEW: evidence confidence for the whole story (§15).
  "evidence_confidence": "HIGH"                   // HIGH | MEDIUM | LOW
}
```

### 5.2 Video seen-state — `data/state/youtube_seen.jsonl`

```jsonc
{
  "video_id": "abc123",
  "channel_id": "UCxxxxxx",
  "channel_name": "drishti_ias_english",
  "url": "https://www.youtube.com/watch?v=abc123",
  "title": "…",
  "description_hash": "sha1:…",       // fingerprint for reprocess detection
  "duration_s": 3612,
  "published_at": "2026-09-14T09:00:00Z",
  "video_class": "DAILY_CURRENT_AFFAIRS",
  "extraction_state": "COMPLETED",   // METADATA_ONLY | CHAPTERS_ONLY | COMPLETED | SKIPPED_BUDGET | FAILED
  "extraction_schema_version": 1,
  "provider": "gemini-video",
  "processed_at": "2026-09-14T09:12:33Z",
  "events_extracted": 5,
  "events_matched_existing": 3,
  "events_enriched": 2,
  "events_published_new": 1,
  "events_rejected": 1
}
```

Used by idempotency (§17) and observability (§19).

### 5.3 Weekly / monthly audits — `data/audits/`

- `data/audits/weekly/YYYY-Www-<channel>.json`
- `data/audits/monthly/YYYY-MM-<channel>.json`

Schema in §13.

---

## 6. Video classification logic (Stage B)

Deterministic order:

1. **Duration filter.** `< min_video_duration_s` (typically 5 min) → `SHORT`
   → drop. `> max_video_duration_s` (90 min) → `LONG_FORM_WORKSHOP` → drop
   for now (revisit under a separate policy).
2. **Live-stream check.** `liveBroadcastContent != "none"` → `LIVE_STREAM`
   → drop.
3. **Title exclusion regex.** Match against `excluded_title_patterns` →
   `COURSE_PROMOTION` → drop.
4. **Class prediction.** Gemini call:

   ```
   Given a YouTube title, description, duration (in minutes), and
   channel name, classify the video into exactly one of the following:

     DAILY_CURRENT_AFFAIRS
     WEEKLY_CURRENT_AFFAIRS
     MONTHLY_CURRENT_AFFAIRS
     SINGLE_TOPIC_EXPLAINER
     EDITORIAL_ANALYSIS
     ECONOMY_RECAP
     SCIENCE_TECH_RECAP
     POLITY_GOVERNANCE
     INTERNATIONAL_RELATIONS
     SPORTS_CURRENT_AFFAIRS
     SHORT
     LIVE_STREAM
     COURSE_PROMOTION
     UNRELATED
     UNKNOWN

   Also produce:
     - language (ISO 639-1)
     - likely_promotional_pct (0–100, integer, how much of the video
       is likely course/coaching promotion based on the description)

   Return JSON only.
   ```
5. **Language filter.** `language != "en"` (or the channel's configured
   language) → `SKIP_NON_MATCH_LANGUAGE`.
6. **Promotional gate.** `likely_promotional_pct > 60` → drop
   (`COURSE_PROMOTION` reclassification).
7. **Route by class:**
   - `DAILY_*` → chapter parse + event pre-match + selective deep.
   - `WEEKLY_*` → coverage-audit path (§13).
   - `MONTHLY_*` → retrospective-significance path (§14).
   - `SINGLE_TOPIC_EXPLAINER` → treat as one candidate event.
   - `EDITORIAL_ANALYSIS` → treat as one candidate with `source_role`
     including `EDITORIAL_ANALYSIS` and higher LLM-scepticism (fact vs
     interpretation, §11).
   - `SHORT` / `LIVE_STREAM` / `COURSE_PROMOTION` / `UNRELATED` → drop.
   - `UNKNOWN` → log to `data/audits/unclassified.jsonl`, skip.

---

## 7. Description / chapter parser design (Stage C)

Deterministic Python. No LLM. Runs before any expensive call.

**Chapter timestamp regex (Python):**

```
^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+[-–—:]?\s*(.+?)\s*$
```

Applied line-by-line to `video.description`. Requires ≥ 3 monotonically
increasing timestamps to accept as a chapter list (single false-positive
"5:30 pm" timestamps get rejected).

**Output:**

```python
@dataclass
class Chapter:
    start_s: int
    end_s: int | None       # filled from next chapter's start; last one from video duration
    label: str              # raw chapter title
    normalized_topic: str   # optional light cleanup: strip emojis, collapse whitespace
```

**Auxiliary extraction from description:**

- **Referenced primary sources** — links matching known primary-source
  domains (rbi.org.in, sebi.gov.in, pib.gov.in, prsindia.org,
  ministry gov.in domains). These become corroboration candidates in §9.
- **PDFs and docs** — direct PDF links in description are stored as
  `referenced_pdfs[]`. Not fetched at this stage — surfaced as candidates
  for the primary-source hydration pass.

**Video without chapters:**

- Set `chapters: []`. Stage D falls back to treating the entire video as
  one topic candidate for the pre-match step. Stage E may still extract
  multiple events from the video via `analyze_video()`.

---

## 8. Deep-video-analysis trigger logic (Stage E)

Deep video understanding is the expensive step. Trigger only when
expected information gain justifies it.

**Per-chapter decision (from Stage D outcomes):**

| Stage D outcome | Deep analysis? | Rationale |
|---|---|---|
| `EXISTING_EVENT_NEEDS_CONTEXT` | **Yes** (segment-only) | We already know the story; we want the specific delta only. Call `analyze_segment(video_url, start, end)` to keep cost bounded. |
| `NEW_POTENTIAL_EVENT` | **Yes** if `predicted_significance ≥ 0.55` else no | Don't spend Gemini calls on things the significance filter will reject. |
| `AMBIGUOUS_EVENT` | Sometimes (budget-gated) | Only if budget remaining and channel has high strength in the topic area. |
| `LOW_RELEVANCE` | No | Skip. |
| `ALREADY_SUFFICIENTLY_COVERED` | No | Merge into existing story's `sources[]` with `access_state: OK`. |

**Budget guards (per-run):**

- `MAX_DEEP_ANALYSIS_CALLS` (default 4 across all channels).
- Per-channel `max_deep_analysis_per_run` (default 2).
- If budget is exhausted mid-run, remaining candidates are downgraded to
  `extraction_state: SKIPPED_BUDGET` and reconsidered in the next cron.

**Whole-video vs segment analysis:**

- Videos with chapters → prefer `analyze_segment()` per accepted chapter.
- Videos without chapters and `duration ≤ 20 min` → `analyze_video()` once.
- Videos without chapters and `duration > 20 min` → `extract_events()`
  with the "identify segments yourself and return event candidates with
  approximate timestamps" prompt shape.

---

## 9. Event extraction schema

Concrete Python dataclass. This is what the `VideoUnderstandingProvider`
returns and what the downstream pipeline consumes.

```python
@dataclass
class EventCandidate:
    # Identity
    video_id: str
    video_url: str
    publisher: str                        # channel display_name
    video_class: str                      # from Stage B
    segment_start_s: int | None
    segment_end_s: int | None

    # Content
    topic: str                            # 8–14 word topic phrase
    what_changed: str                     # ≤ 30 words
    why_it_matters: str                   # ≤ 30 words; may be "" if not clearly stated
    important_facts: list[FactClaim]      # see §11 for fact vs interpretation split
    numbers_dates: list[str]              # normalised
    entities: list[str]
    regions: list[str]                    # ISO codes + GLOBAL
    referenced_primary_sources: list[str] # URLs mentioned in-video that we could hydrate

    # Categorisation hints (feed into the same categorize step downstream)
    suggested_main_category: str          # AI | TECH | SCIENCE | ...
    suggested_sub_category: str | None
    story_type: str                       # ANNOUNCEMENT | POLICY_CHANGE | ... (§6 of 2026-09-14 review)
    impact_scope: str                     # GLOBAL | REGIONAL | NATIONAL | LOCAL | SECTOR | NICHE
    importance: str                       # MAJOR | NOTABLE | ROUTINE
    india_relevance: str                  # HIGH | MEDIUM | LOW | NONE
    business_relevance: str
    technology_relevance: str

    # Provenance & confidence
    confidence: float                     # 0.0–1.0, provider-reported
    source_role: str                      # SECONDARY_EXPLAINER (default for these channels)

    # Rate-limiting / audit
    extraction_schema_version: int
    provider: str
    model: str


@dataclass
class FactClaim:
    text: str
    kind: str                             # FACT_CLAIM | CONTEXT | INTERPRETATION | OPINION |
                                          #   FORECAST | EXAMPLE | TEACHING_ANALOGY
    confidence: float
```

**Design intent:**

- **`what_changed` and `why_it_matters` are separate strings** so the
  refine step can lift them cleanly (matches the three-level card design
  in yesterday's UX review).
- **`important_facts` is not a bag of strings** — it's typed by
  `FactClaim.kind`. Interpretation and opinion do not silently become
  fact (brief §10).
- **`referenced_primary_sources`** enables the corroboration pass in §11.
- **`suggested_*` are hints, not decisions.** The normal categorize step
  still runs; the LLM's own hint is passed in the prompt so it can agree
  or override.

---

## 10. Event matching / deduplication design

Uses the two-stage cluster model already proposed in the `2026-09-14`
review (§7 there). YouTube-derived candidates are just another input to
that model, with two adjustments:

**Adjustment 1 — Stage 1 (MiniLM) uses the topic phrase, not the full video.**
Embedding a 30-min transcript against 100 existing stories would be noisy.
Instead, embed `what_changed + " " + topic + " " + " ".join(entities)`
against the same 3-day window of story summaries.

**Adjustment 2 — Stage 2 classifier gets a source-role hint.**
The classifier already emits one of `SAME_EVENT_SAME_DEV /
SAME_EVENT_NEW_DEV / DIFFERENT_EVENT`. For YouTube candidates, the
classifier prompt includes an extra note: *"The candidate is a
secondary explainer of the same event. Prefer SAME_EVENT_SAME_DEV
unless the explainer surfaces a genuinely new development
(implementation date announced, new numbers, new decisions)."*

**Outcome mapping:**

| Cluster outcome | Action |
|---|---|
| `SAME_EVENT_SAME_DEV` | **Enrich existing story.** Add `enrichment_deltas[]` via §11 delta pipeline. Do **not** create a new card. Append YouTube link to `sources[]` with `source_role: SECONDARY_EXPLAINER`. |
| `SAME_EVENT_NEW_DEV` | Retain as **new event update** inside the existing cluster. Feeds normal downstream pipeline. |
| `DIFFERENT_EVENT` | Retain as **new candidate**, feeds normal downstream pipeline. |
| Below cluster threshold + no match | **New candidate.** |

---

## 11. Enrichment algorithm (delta-based)

Brief §12 is explicit: do not rewrite an already-good story. Compare and
attach only useful deltas.

**Delta types:**

```
CONTEXT               — historical background not in existing summary
CONSEQUENCE           — clear downstream effect not stated
AFFECTED_GROUPS       — specific stakeholders named in the explainer
IMPLEMENTATION_DETAIL — dates, mechanisms, thresholds
PRIOR_POLICY          — the previous law/policy referenced
REDUNDANT             — repeat of an already-summarised fact (do NOT attach)
UNSUPPORTED           — interpretation or teaching analogy (do NOT attach)
```

**Algorithm:**

```
INPUT:
  existing_story.summary
  existing_story.key_points[]          # from refine layer 4
  event_candidate.what_changed
  event_candidate.why_it_matters
  event_candidate.important_facts[]    # each with kind

STEPS:

  1. Filter event_candidate.important_facts:
       drop any where kind in {INTERPRETATION, OPINION, FORECAST,
                                TEACHING_ANALOGY}
       (they never become story facts).

  2. For each remaining FactClaim f:
       run string-similarity + entity/number overlap against
       existing_story.key_points[]:
         if match ≥ 0.75  → mark REDUNDANT, skip.
         else             → propose as delta candidate.

  3. For each proposed delta:
       classify delta_type via a short Gemini call
       (or heuristic — dates → IMPLEMENTATION_DETAIL,
        numbers about people → AFFECTED_GROUPS,
        past-tense references → PRIOR_POLICY / CONTEXT).

  4. Confidence assignment (§15):
       if delta_type ∈ {IMPLEMENTATION_DETAIL, PRIOR_POLICY}
         and provider.confidence ≥ 0.7 → HIGH
       elif provider.confidence ≥ 0.6 → MEDIUM
       else                            → LOW

  5. Persist delta with full provenance (§14).
```

**Cap:** at most 4 attached deltas per story. If more are extracted,
keep the top-4 by `(delta_type_priority, confidence)`.

**Consequence for the UI (yesterday's design review, Level 3):** the
`CONTEXT` section on the expanded card is *populated by these deltas*,
labelled by `delta_type`, sourced by `provenance.publisher`. This is the
concrete data path the Level-3 UI was waiting for.

---

## 12. New-event publication decision logic

For a Stage D outcome of `NEW_POTENTIAL_EVENT`, the candidate becomes a
pseudo-Candidate in the existing pipeline. Decision rules:

- **Significance gate.** Run `significance_v2` (or v3 per the earlier
  design review) on the candidate. `score < 0.55` → drop.
- **Corroboration check.** If `source_role_count == 1` (only the YouTube
  explainer) AND `evidence_confidence == LOW`, hold back. Attempt one
  corroboration pass:
  - For each `referenced_primary_source` in the candidate, HEAD-check the
    URL. If reachable and extractable (e.g. a PIB press release URL),
    hydrate it as a **primary source**, run the normal
    `fetch → extract` on it, and elevate `evidence_confidence` to `HIGH`.
  - If no corroboration is found and the candidate is `MAJOR` importance
    AND `impact_scope ∈ {GLOBAL, NATIONAL}`, still publish — but with
    `evidence_confidence: LOW` and a UI treatment that surfaces this
    (yesterday's design review has "sources: N — 1 explainer only" copy).
  - Otherwise (single explainer + not-major) → drop, log to
    `data/audits/single_explainer_drops.jsonl` for weekly review.
- **Provenance discipline (brief §8):** if a YouTube explainer states
  *"according to today's Hindu…"* and we did not access The Hindu, the
  story's `sources[]` **does not** include The Hindu. It records the
  explainer citing The Hindu (`referenced_but_not_accessed: ["The Hindu"]`).
  This is a schema field, not a UI element (surfaced only in Level 3).

---

## 13. Daily / weekly / monthly behavioural differences

### 13.1 Daily current-affairs videos

**Purpose:** discovery + enrichment.

**Pipeline path:** full Stage A → F.

**Outputs:**

- Enrichment of existing stories (§11).
- New candidates for the normal feed (§12).
- Rejected UPSC trivia (never enters the feed; logged for audit).

### 13.2 Weekly current-affairs videos

**Purpose:** coverage-audit only. **Never publishes a story directly.**

**Pipeline path:** Stage A → B (class = `WEEKLY_*`) → C (chapters) →
D (pre-match against last 7 days of feed) → audit output.

**Output — `data/audits/weekly/YYYY-Www-<channel>.json`:**

```jsonc
{
  "source": "drishti_ias_english",
  "video_id": "…",
  "video_url": "…",
  "week_of": "2026-W37",
  "topics_detected": 31,
  "matched": 24,
  "potential_misses": [
    {
      "topic": "…",
      "chapter_start_s": 1520,
      "chapter_end_s": 1830,
      "why_missed_hypothesis": "no source ingested this beat",
      "verdict": "PENDING"    // PENDING | CONFIRMED_MISS | ALREADY_REPRESENTED |
                              //   CORRECTLY_EXCLUDED | SOURCE_GAP |
                              //   CATEGORIZATION_ERROR | SIGNIFICANCE_ISSUE |
                              //   DELAYED_EVENT | UPSC_TRIVIA
    }
  ],
  "confirmed_misses": [],
  "correctly_excluded": []
}
```

**How verdicts are assigned:**

- **Auto:** if a MiniLM search against the last-7-day feed at threshold
  0.75 (lower than dedup's 0.82, deliberately looser for audit) finds a
  match → `ALREADY_REPRESENTED`.
- **Auto:** if the topic's primary entities include exam-oriented
  keywords (`GS Paper`, `Prelims`, `Mains`, `syllabus`, `previous year
  question`, `PYQ`, `mock test`) → `UPSC_TRIVIA`.
- **Auto:** if predicted significance < 0.20 → `CORRECTLY_EXCLUDED`.
- **Otherwise:** `PENDING` — surfaces in a weekly audit report file the
  owner can review. No auto-injection into feed.

**No fresh cards** — this preserves brief §14 "Do NOT automatically
inject all weekly topics into the current feed."

### 13.3 Monthly current-affairs videos

**Purpose:** retrospective significance calibration.

**Pipeline path:** Stage A → B (class = `MONTHLY_*`) → C → D against the
**full 30-day feed**.

**Output — `data/audits/monthly/YYYY-MM-<channel>.json`:**

```jsonc
{
  "source": "drishti_ias_english",
  "video_id": "…",
  "month": "2026-09",
  "topics_in_monthly_recap": 45,
  "matched_to_feed_stories": [
    {
      "topic": "…",
      "matched_story_ids": ["…"],
      "days_since_first_ingest": 12,
      "appeared_in_daily": true,
      "appeared_in_weekly": true,
      "retrospective_importance_bump": 0.10
    }
  ],
  "unmatched_but_important_stories_in_feed": [
    { "story_id": "…", "note": "not in Drishti monthly — worth a second look" }
  ]
}
```

**Effect:** stories that appear in a Drishti/Unacademy monthly recap
get a `retrospective_importance` bump written back onto their record.
This is a signal for the ranker over time — a story that survived to a
monthly recap was worth keeping. **It is not republished as breaking
news** (brief §15).

---

## 14. Provenance design

Every enriched fact, delta, or event candidate carries a provenance
block. Stored internally, not necessarily displayed.

```jsonc
{
  "source_id": "drishti_ias_english",
  "source_role": "SECONDARY_EXPLAINER",
  "publisher": "Drishti IAS English",
  "video_id": "abc123",
  "video_url": "https://www.youtube.com/watch?v=abc123",
  "segment_start_s": 1110,
  "segment_end_s": 1515,
  "retrieved_at": "2026-09-14T12:03:11Z",
  "provider": "gemini-video",
  "model": "gemini-3.5-flash-lite",
  "extraction_schema_version": 1,
  "prompt_version": "yt-event-extract-v1",
  "content_hash": "sha1:…"
}
```

**Why every field matters:**

- `source_id` + `source_role` — routing and UI grouping.
- `video_id` + `segment_start_s/end_s` — allows a future
  "Watch explainer at 18:30" deep-link.
- `extraction_schema_version` + `prompt_version` — enables deliberate
  reprocessing when we improve the extraction (§17).
- `content_hash` — a hash of the (video_id, segment_start, segment_end,
  extracted content). Lets us detect drift between reprocesses.

---

## 15. Confidence / evidence design

Two independent confidence signals:

**1. Per-fact confidence (`FactClaim.confidence`)**

- Set by the extraction provider on each fact claim.
- Governs whether a fact is attached to `enrichment_deltas[]`.

**2. Per-story evidence confidence (`Story.evidence_confidence`)**

- Computed:

  ```
  role_score = 0.6 if any(role in sources[] for role in PRIMARY_OFFICIAL,
                                                     INDEPENDENT_REPORTING)
             else 0.3 if SECONDARY_EXPLAINER only
             else 0.1
  count_score = min(len(distinct source_roles present) / 3, 1.0) * 0.4

  raw = role_score + count_score
  HIGH   if raw ≥ 0.7 or ≥ 2 INDEPENDENT_REPORTING sources
  MEDIUM if raw ∈ [0.4, 0.7)
  LOW    otherwise
  ```

**UI treatment (references yesterday's UX review):**

- `HIGH` → no special marker.
- `MEDIUM` → subtle marker on Level 2 ("secondary sources").
- `LOW` → explicit line on Level 2: "One explainer, no corroboration yet."

Never displayed as a percentage. Never used to gate display (per brief §25:
"Do NOT show crude confidence percentages to the user unless there is a
strong UX reason"). Used internally to gate whether the story is
published in the first place (§12).

---

## 16. Cost / quota controls

**Per-run budgets (configurable in `youtube_sources.yaml` + env):**

| Control | Default | Rationale |
|---|---|---|
| `MAX_NEW_VIDEOS_PER_CHANNEL_PER_RUN` | 6 | Roughly one day's Drishti volume + safety margin |
| `MAX_TOTAL_NEW_VIDEOS_PER_RUN` | 15 | Global cap across channels |
| `MAX_VIDEO_MINUTES_PER_RUN` | 240 | Wall-clock ceiling on deep analysis |
| `MAX_DEEP_ANALYSIS_CALLS` | 4 | Each Gemini video call is 10–60 s + $-visible |
| `MAX_WEEKLY_AUDIT_VIDEOS` | 2 | Two channels × one weekly each |
| `MAX_MONTHLY_AUDIT_VIDEOS` | 2 | Same, per month |
| `YT_API_QUOTA_UNITS_PER_RUN` | 100 | Well within 10,000/day free tier |

**YT Data API v3 cost budget:**

- `channels.list` (once per channel per run): 1 unit
- `playlistItems.list` (page-size 20): 1 unit
- `videos.list` (batch 50): 1 unit

Per run: ~5–10 units total across both channels. 3 crons/day = ~30
units/day. Free-tier quota is 10,000. Massive headroom.

**Gemini cost:**

- Metadata classify per new video: ~1k tokens in, ~200 out.
- Deep video analyze: model-priced by video minutes. Budget-gated to 4
  calls/run → ceiling on cost.
- **Expected marginal spend: < $2/month** at the described budgets. This
  is the reason budgets exist — not because we're near a cost cliff, but
  because runaway loops on a bad prompt could cross the cliff quickly.

---

## 17. Caching / idempotency design

**Video-level idempotency (`data/state/youtube_seen.jsonl`):**

```
processed_key = (video_id, extraction_schema_version, prompt_version)
```

- If a video has been processed with the current `(schema, prompt)` and
  `description_hash` is unchanged → **skip**. Reuse extracted events.
- If `description_hash` changed (creator edited chapters) → **reprocess
  Stage C onwards**. Metadata classification is cached.
- If `extraction_schema_version` bumps (we widened the schema) → **full
  reprocess** on next run.
- If `prompt_version` bumps → full reprocess.

**Cluster-level idempotency:**

- Cluster IDs are content-hash-derived (yesterday's §7). YouTube
  candidates joining an existing cluster do **not** create new cluster IDs.
- Story IDs remain stable across enrichment. A YouTube delta appended to
  an existing story does not change `story.id` — enabling frontend
  `completed[story.id]` state to survive (yesterday's UX review §17).

**Manifest write ordering:**

- Enrichment deltas append; they do not rewrite `summary`.
- Only if the story is being re-refined does `summary` change, and even
  then we bump a `summary_version` counter so the frontend can detect a
  change and re-cache.

---

## 18. Error handling

Brief §27 explicitly lists failure modes. Each has a policy:

| Failure | Policy |
|---|---|
| Video deleted / private | Log to `youtube_seen.jsonl` with `extraction_state: NOT_ACCESSIBLE`. Never retry. |
| Unlisted / age-restricted | Same as deleted. |
| Gemini unable to process URL | Fall back: keep metadata + chapters; produce metadata-only event candidates from chapter labels. `extraction_state: METADATA_ONLY`. |
| YT Data API quota exceeded | Skip discovery for the rest of the run. Cron next run retries. Alert file `data/audits/quota_exhaustion.jsonl`. |
| Malformed chapters | Fall through to whole-video analysis (Stage D → E). |
| Missing description | Same. |
| Live stream not finished | Skip; will be discovered again when it ends. |
| Shorts | Filtered at Stage B by duration. |
| Video is mostly promotional | Filtered at Stage B by `likely_promotional_pct`. |
| Extraction returns no events | Log to `data/audits/empty_extractions.jsonl`. Not a pipeline failure. |
| Non-English content | Filtered at Stage B by language. If unrelated channel starts producing Hindi, `enabled: false` via config. |
| Duplicate weekly / monthly videos | Cache by (channel, video_class, week/month key). Skip second one. |
| False event match | Cluster classifier gets it wrong → surfaces in weekly audit as "over-merge". Manual verdict. |
| Provider / model outage | `VideoUnderstandingProvider.can_process()` returns False. Skip. |
| **Any single failure** | **MUST NOT** fail the news pipeline. Wrap Stage A–F in try/except; log to `data/audits/youtube_errors.jsonl` and continue. |

---

## 19. Observability

Per-run counters, written to `data/audits/youtube_run_<timestamp>.json`:

```jsonc
{
  "run_id": "…",
  "started_at": "2026-09-14T12:00:00Z",
  "duration_s": 143.2,
  "per_channel": {
    "drishti_ias_english": {
      "videos_discovered": 3,
      "videos_new": 1,
      "videos_skipped": 2,
      "videos_metadata_only": 0,
      "videos_deep_processed": 1,
      "events_extracted": 5,
      "events_matched_existing": 3,
      "events_enriched": 2,
      "events_new_candidates": 2,
      "events_rejected": 1,
      "video_processing_failures": 0,
      "cost_estimate_usd": 0.08
    },
    "unacademy_ias_english": { … }
  },
  "weekly_possible_misses": 4,
  "weekly_confirmed_misses": 0,
  "monthly_recurrence_hits": 7
}
```

**Aggregation (P1):** a small `pipeline/youtube_report.py` script reads
the last 30 days of these files and produces a rolled-up dashboard
markdown. Not a hosted dashboard; just a checked-in artefact for owner
review.

**No Grafana. No Datadog.** Brief §28 explicitly forbids these.

---

## 20. Copyright / content-handling safeguards

Explicit rules encoded in prompts and post-processing:

1. **No verbatim reproduction.** The extraction prompt includes
   *"Rephrase in Briefing's own words. Do not include long verbatim
   passages from the video."*
2. **Verbatim-length guard.** Post-process: any extracted string
   ≥ 20 words that appears verbatim in the video description or previous
   Briefing extractions of the same channel → flag as
   `verbatim_leak`, drop the delta, log to
   `data/audits/verbatim_leaks.jsonl`.
3. **No transcript persistence.** Full transcripts (if ever obtained
   through the provider) are **not** stored. Only structured
   extraction is persisted. The `data/state/youtube_seen.jsonl` schema
   deliberately omits a transcript field.
4. **Paywall reconstruction guard.** If an EventCandidate cites a
   paywalled source (e.g., "The Hindu said…"), the pipeline **never**
   presents the reconstructed information as directly ingested from that
   source. `sources[]` records only the explainer; the paywalled outlet
   is recorded under `referenced_but_not_accessed` (§12) which never
   appears in `sources[]`.
5. **UI attribution.** Level 3 always renders the explainer with the
   `explainer` label, distinct from `official` and `reporting` (brief §24,
   yesterday's UX review §11).

---

## 21. Files expected to change

Additions:

- `pipeline/youtube.py` — new, top-level module. Contains stages A–F.
- `pipeline/video_understanding.py` — new. `VideoUnderstandingProvider`
  protocol + `GeminiVideoProvider` implementation.
- `pipeline/youtube_sources.yaml` — new, declarative registry.
- `pipeline/chapter_parser.py` — new, deterministic regex parser.
- `pipeline/youtube_audit.py` — new, weekly + monthly audit writers.
- `data/state/youtube_seen.jsonl` — managed at runtime.
- `data/audits/{weekly,monthly}/*.json` — managed at runtime.
- `data/audits/youtube_run_*.json` — observability output.

Modifications (small, well-scoped):

- `pipeline/run.py` — invoke `youtube.run(cfg)` after the existing news
  fetch, before dedup. YouTube events either become enrichment deltas
  (attached to existing stories mid-pipeline) or become
  candidates that continue through the normal pipeline.
- `pipeline/manifest.py` — persist new story fields (`sources[]` with
  `source_role`, `enrichment_deltas[]`, `evidence_confidence`,
  `source_roles_present`, `referenced_but_not_accessed`).
- `pipeline/dedup.py` / new `pipeline/cluster.py` — reuse the same
  cluster model from yesterday's design review. YouTube candidates enter
  via the same code path.
- `pipeline/config.py` — new env vars (`YOUTUBE_API_KEY`,
  budget knobs).

Not modified:

- `pipeline/tts.py`, `pipeline/normalize.py`, `pipeline/audio_validate.py`.
- Frontend, in this doc's scope — but the enrichment-delta fields
  described in §5 are what yesterday's Level 3 UI already assumes.

---

## 22. Backward compatibility

- All new fields are additive with safe defaults.
- Legacy stories without `sources[].source_role` render as
  `INDEPENDENT_REPORTING` (best-guess default).
- Legacy stories without `evidence_confidence` render without a badge.
- Legacy stories without `enrichment_deltas[]` show no Level-3 context
  section — same as today.
- The `2026-09-14` design review's proposed cluster model is a hard
  prerequisite. If it hasn't shipped yet, the YouTube design still works
  but degrades to drop-only dedup and never enriches — Stage F path (1)
  is skipped, path (2) still functions.

---

## 23. Unit / integration test plan

### 23.1 Unit tests

- `pipeline/chapter_parser.py` — table-driven tests:
  - description with valid chapters at `00:00`, `04:45`, `18:20`, `31:10`,
    `47:50` → 5 chapters, monotonic, `end_s` filled from next `start_s`
    (last from duration).
  - description with only two timestamps → rejected (`<3` chapters).
  - description with "5:30 pm meeting" (false positive) → rejected
    because not monotonically increasing.
  - description with mixed `HH:MM:SS` and `MM:SS` → both parsed.
- `pipeline/youtube.py::classify_video` — mock LLM, table-driven inputs.
- `pipeline/youtube.py::should_deep_analyze` — decision table.
- Enrichment delta classifier — the § 11 algorithm on a fixture set of
  (existing_story, event_candidate) pairs.

### 23.2 Integration tests

- **Golden video fixtures.** Check in 6 fixture files:
  - `tests/fixtures/youtube/drishti_daily_2026-09-11.json` — metadata +
    description of a real daily video.
  - `tests/fixtures/youtube/drishti_weekly_2026-W36.json`
  - `tests/fixtures/youtube/drishti_monthly_2026-08.json`
  - `tests/fixtures/youtube/unacademy_daily_2026-09-12.json`
  - `tests/fixtures/youtube/drishti_promotional.json` — mostly ad.
  - `tests/fixtures/youtube/single_topic_explainer.json`
- Each fixture pins expected: `video_class`, `chapters`, and the six
  event-matching test cases from §30 of the brief.

### 23.3 Event-matching test cases (brief §30)

| Case | Fixture | Expected |
|---|---|---|
| **A** — Same event, added context | daily video mentions RBI change already in feed | No duplicate. `enrichment_deltas[]` attached with `PRIOR_POLICY` + `AFFECTED_GROUPS`. |
| **B** — New national policy, PIB confirms | Unacademy daily + PIB URL in description | New story, `sources = [PIB, Unacademy explainer]`. `evidence_confidence: HIGH`. |
| **C** — Drishti mentions paywalled Hindu article, PIB confirms | daily video | Story published with PIB as primary source + Drishti as explainer. Hindu recorded under `referenced_but_not_accessed`, NOT in `sources[]`. |
| **D** — Only Drishti covers the event | daily video, no corroboration URLs | If significance ≥ 0.55 AND MAJOR + NATIONAL/GLOBAL → publish with `evidence_confidence: LOW`. Otherwise drop, log to `single_explainer_drops.jsonl`. |
| **E** — Weekly recap surfaces a miss from 5 days ago | weekly fixture | Recorded as `PENDING` miss in `data/audits/weekly/`. NOT injected as fresh news. |
| **F** — Monthly recap repeats a major story | monthly fixture | `retrospective_importance` bump on the existing story record. No new card. |

### 23.4 Evaluation set (brief §29)

Persisted at `pipeline/eval/youtube_manual_labels.json`. Contains at
least: 3 Drishti daily, 3 Unacademy daily, 1 weekly, 1 monthly, 1
promotional video, 1 single-topic explainer, 1 video with chapters, 1
video without chapters. For each: human-labelled expected events with
timestamps.

**Metrics computed against this set:**

- `event_recall` = extracted events / manually-labelled events.
- `event_precision` = correct extracted events / total extracted events.
- `duplicate_rate` = duplicates as % of published cards.
- `false_enrichment_rate` = attached deltas that reviewer marks
  incorrect / total attached deltas.
- `promotion_leakage` = promotional segments that leaked into events.
- `fact_vs_opinion_accuracy` = correct `FactClaim.kind` labels.
- `event_matching_accuracy` = cluster-outcome agreement with reviewer.

**Ship gate:** `event_recall ≥ 0.75`, `event_precision ≥ 0.85`,
`duplicate_rate ≤ 0.05`, `promotion_leakage == 0.0`.

---

## 24. Representative evaluation dataset

Build once, keep. Owner-labelled. Structure:

```jsonc
{
  "video_id": "…",
  "channel": "drishti_ias_english",
  "class": "DAILY_CURRENT_AFFAIRS",
  "expected_events": [
    {
      "topic": "RBI monetary policy review",
      "segment_start_s": 285,
      "segment_end_s": 1100,
      "expected_main_category": "BUSINESS",
      "expected_impact_scope": "NATIONAL",
      "expected_importance": "MAJOR",
      "expected_cluster_outcome_against_2026-09-14_feed": "SAME_EVENT_SAME_DEV",
      "expected_deltas": ["PRIOR_POLICY", "IMPLEMENTATION_DETAIL"],
      "notes": "…"
    }
  ],
  "expected_drops": [
    { "segment_start_s": 3400, "reason": "UPSC exam-tips segment" }
  ]
}
```

Kept under `pipeline/eval/youtube_manual_labels.json`. Ten fixtures is
enough to bootstrap; grow to 30 during Phase 3.

---

## 25. Browser / product implications

This design produces new data fields but no new **primary** UI. The
UI implications ride on yesterday's `2026-09-14` UX review:

- **Level 1 SCAN card:** unchanged, unless the story is explainer-only
  → `evidence_confidence: LOW` → subtle "explainer-only" affordance
  under the source line (not on the card itself; on Level 2).
- **Level 2 BRIEF:** the "Sources" section renders `source_role` as
  small labels: `official` / `reporting` / `explainer`. If any
  `enrichment_deltas[]` are present, a "Watch explainer at 18:30" link
  appears with the segment deep-link (`&t=1110s`).
- **Level 3 DEPTH:** the `CONTEXT` block is populated by
  `enrichment_deltas`, labelled by `delta_type`. Format:

  ```
  CONTEXT
    Prior policy: <content>            — Drishti IAS English (explainer)
    Affected groups: <content>         — Drishti IAS English (explainer)
    Implementation detail: <content>   — Unacademy IAS English (explainer)
  ```

- **No video thumbnails or player embeds** on the main feed. YouTube
  remains an internal source of understanding, not a visual mode
  (brief §16, yesterday's UX review §16).

---

## 26. Risks and unknowns

### Risks

- **Gemini YouTube URL feature availability.** This is a Google feature
  that has changed pricing/quotas before. Mitigation: the provider
  abstraction (§3, §21). If the feature is deprecated, we downgrade to
  metadata-only extraction and the pipeline degrades gracefully.
- **YT Data API v3 quota drift.** Free tier is 10,000 units/day; our use
  is ~30. But YouTube has historically tightened quotas without notice.
  Mitigation: quota-check code + weekly audit that flags approaching
  limits.
- **Explainer fabrication.** Educators sometimes state things
  confidently that are wrong or dated. Mitigation: corroboration step
  (§12), `FactClaim.kind` typing (§11), `evidence_confidence: LOW`
  path when single-source.
- **UPSC trivia leakage.** Drishti/Unacademy content is optimised for
  exam relevance, which is a different persona. Mitigation: the
  metadata-classification gate + the significance filter + the
  `UPSC_TRIVIA` verdict on weekly audit.
- **Enrichment bloat.** Attaching every delta would balloon `feed.json`
  and Level-3 UI. Mitigation: 4-delta cap + `REDUNDANT` filter (§11).
- **Cluster classifier over-merging.** A YouTube explainer that
  summarises 5 topics in a single segment could be classified as a
  single-event match to only one. Mitigation: chapter parsing (Stage C)
  and per-chapter event extraction (Stage E) — never let one video's
  segment collapse into one enrichment record.
- **Copyright brittleness.** The verbatim-length guard (§20) is
  conservative; a subtle rephrase might still be too close to source.
  Mitigation: brief-mandated "concise original briefing language"
  prompt + owner spot-check during evaluation.
- **Provider cost spike.** A single 90-min video analysed at model
  cost could exceed the daily Gemini spend the rest of the pipeline
  uses. Mitigation: `MAX_DEEP_ANALYSIS_CALLS` + `MAX_VIDEO_MINUTES_PER_RUN`
  + segment-only analysis for `EXISTING_EVENT_NEEDS_CONTEXT`.

### Unknowns

- Whether Gemini's YouTube URL analysis reliably respects
  segment-time boundaries. Needs validation against fixtures.
- Whether Drishti/Unacademy chapters are consistent enough for the
  regex to hit ≥ 80 % coverage. Needs sampling.
- What fraction of daily videos are `COURSE_PROMOTION`-heavy. Affects
  budget planning.
- How long it takes for a Hindu paywalled article to be corroborated by
  an accessible source (PIB, PRS). Affects the `single_explainer_drops`
  ratio.
- Whether the extraction schema will need a `local_language_original`
  field for the Hindi-variant channels the owner may add later.

---

## Priority classification

Read as: **P0** = required to correct the product model or the design
falls apart; **P1** = strong improvement; **P2** = polish.

- **P0** — YT Data API discovery + metadata classification + chapter
  parser + `VideoUnderstandingProvider` abstraction.
- **P0** — Event-candidate schema + downstream integration with the
  existing categorize / significance / dedup / refine pipeline.
- **P0** — Delta-based enrichment (never rewrite existing summary).
- **P0** — Provenance discipline: never label an explainer as the
  original source of a paywalled article.
- **P0** — Weekly = coverage-audit-only; Monthly = retrospective-only.
  Never inject weekly/monthly as fresh cards.
- **P0** — Error handling that never fails the parent news pipeline.
- **P0** — Cost/quota budgets with per-run caps.
- **P1** — Corroboration pass on `referenced_primary_sources`.
- **P1** — Onboarding gate for future channels (`quality_gate:
  unverified` shadow-run).
- **P1** — Aggregated observability markdown roll-up.
- **P1** — `retrospective_importance` signal from monthly audit
  feeding back into `significance_v2`.
- **P2** — "Watch explainer at 18:30" segment deep-link in the UI.
- **P2** — Non-English channel support.

---

## Consistency review

Verifying the design against each rule the brief lays down:

| Brief requirement | Status | Note |
|---|---|---|
| Do NOT bypass paywalls | ✅ | §12, §20. Paywalled outlets never appear in `sources[]` without direct extraction. |
| Do NOT scrape restricted publisher content | ✅ | We only ingest what Gemini can process from a public URL. |
| Do NOT imply an article was read that wasn't | ✅ | §12 `referenced_but_not_accessed` field. |
| Do NOT fabricate a summary from a headline | ✅ | Level-0 extraction requires body access; YouTube extraction requires actual segment analysis. |
| Additional channels via configuration | ✅ | §4 declarative registry. |
| No YouTube scraper | ✅ | §3. Only YT Data API v3 + Gemini video URL. |
| No yt-dlp / caption scraping | ✅ | §3. Explicitly excluded. |
| VideoUnderstandingProvider abstraction | ✅ | §3, §21. |
| Gemini-specific handling stays behind the interface | ✅ | Only `pipeline/video_understanding.py` imports Gemini. |
| Cheap-first staged processing | ✅ | §2 Stages A → F. |
| No giant one-story-per-video | ✅ | §5 event-candidate model, §7 chapter parser, §9 schema. |
| Orthogonal metadata participation | ✅ | §9 EventCandidate carries the full orthogonal schema from yesterday's review. |
| Source-role model | ✅ | §5.1 `sources[].source_role`. |
| Never label secondary as primary reporting | ✅ | §12, §14, §20, §25. |
| YouTube can be a valid secondary basis | ✅ | §12 corroboration path + `evidence_confidence: LOW` path for single-explainer + MAJOR. |
| Fact / interpretation / opinion split | ✅ | §9 `FactClaim.kind`, §11 filter drops non-fact kinds. |
| Event matching + delta enrichment | ✅ | §10, §11. |
| Never duplicate on secondary re-coverage | ✅ | §10 `SAME_EVENT_SAME_DEV` → enrich, no new card. |
| Delta-based enrichment | ✅ | §11 filters `REDUNDANT` and `UNSUPPORTED`. |
| Daily = discovery + enrichment | ✅ | §13.1. |
| Weekly = coverage audit | ✅ | §13.2. Never publishes fresh. |
| Monthly = retrospective significance | ✅ | §13.3. `retrospective_importance` bump, no republish. |
| Declarative channel registry | ✅ | §4. |
| Onboarding / quality gate | ✅ | §17 P1 note, §4 `quality_gate: unverified` shadow. |
| Promotional content removal | ✅ | §6 title regex + `likely_promotional_pct` gate. |
| Do NOT persist verbatim transcripts | ✅ | §17, §20. No transcript field. |
| Idempotency + caching | ✅ | §17 (schema_version, prompt_version, description_hash). |
| Processing budget controls | ✅ | §16. |
| Augment (not replace) existing news sources | ✅ | The news pipeline is untouched; YouTube is an add-on stage. |
| Content provenance | ✅ | §14. |
| Restrained user-facing source presentation | ✅ | §25. Explainer distinct from official/reporting. |
| Claim confidence (internal) | ✅ | §15. HIGH/MEDIUM/LOW; no percentages in UI. |
| Non-UPSC future channels | ✅ | §4 `strengths` map is topic-generic; no UPSC assumptions in code. |
| Failure modes handled | ✅ | §18 table. Pipeline never fails on one video. |
| Observability without Grafana/Datadog | ✅ | §19. JSON files under `data/audits/`. |
| Validation set + representative eval | ✅ | §23, §24. |
| Copyright safeguards | ✅ | §20. |
| Security: secret management | ✅ | Same GHA secrets pattern as `GEMINI_API_KEY`. New `YOUTUBE_API_KEY`. |
| No OAuth / no personal YouTube access | ✅ | §3 API key only. |
| No unnecessary infrastructure | ✅ | No queues, no vector DBs, no agent frameworks. Pure Python stages. |

**Nothing in this design proposes:**

- Downloading videos.
- Storing full transcripts.
- Scraping timed-text endpoints.
- Bypassing YouTube's ToS.
- Republishing creator content verbatim.
- Reconstructing paywalled articles.
- Introducing Kafka / Kubernetes / Celery / vector DBs / LangChain / agent
  frameworks (brief §33).
- Turning Briefing into a video product.
- Replacing existing primary sources.

---

**End of YouTube integration design review.** Awaiting approval before
touching code.
