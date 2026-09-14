# Design Review — 2026-09-14

Response to the external critique in `log2.txt`. **Analysis and design only —
no code modified.** Recommendations are classified P0 (required to correct
product model) / P1 (strong improvement) / P2 (optional polish). Every
recommendation is connected to either the re-anchored persona or a
demonstrated issue in the current implementation.

---

## 1. Verified current behavior

Cross-checked the critique against `site/src/pages/index.astro`,
`site/src/components/Feed.tsx`, `site/src/components/Blogs.tsx`,
`pipeline/significance.py`, `pipeline/dedup.py`, `pipeline/categorize.py`,
`pipeline/refine.py`, and `pipeline/manifest.py`.

**Confirmed:**

- **Hero emphasises volume, not change.** `index.astro:36-39` renders
  `{stories.length} stories · {totalMinutes} min listen · {uniqueSources}
  sources`. Framed as a workload, not as "what changed."
- **"N°01 / Today" is per day-group, not per feed.** `Feed.tsx:454-468`
  applies the lede cue when `i === 0` inside every `day-group`, so
  historical days each display their own "N°01 / Today" — semantically
  wrong for days that are no longer today.
- **"refined by hand" is inaccurate.** `index.astro:44` says "refined by
  hand." The refinement is fully automated (six Gemini + regex passes).
- **`read` / `article` copy is ambiguous.** `Feed.tsx:509-517` exposes
  `article ↗` (external publisher) and `read` (expand summary). Two
  destinations, both plausible readings.
- **No played / listened state.** Nothing in `Feed.tsx` tracks which
  stories the user has completed. Only age-based dimming (`ageBucket`,
  lines 91-96) at >18h and >48h.
- **Globe is a top-level view toggle**, equal in prominence to List
  (`Feed.tsx:359-374`).
- **`sources[]` chip** appears only when `sources.length > 1`
  (`Feed.tsx:501-508`). Visible but small.
- **Feed is chronological grid**, not "since last check". No CATCH UP,
  no WORTH KNOWING, no state of caught-up-ness.
- **`significance_v2` T1** penalises non-actionable stories by −0.2
  (`pipeline/significance.py`). Directly demotes record-breaking wins,
  championship results, scientific discoveries — high-value informational
  stories.
- **`dedup.py`** is drop-only. Cosine ≥ 0.82 → skip. No event clustering,
  no follow-up detection. Same-event new-development stories are treated
  the same as duplicate reports.
- **No orthogonal metadata.** Story schema is `main`, `sub`,
  optional `location`. No `topics[]`, `entities[]`, `regions[]`,
  `story_type`, `impact_scope`, `importance`, `sport`, `competition`,
  `athletes_or_teams[]`, `event_id`.
- **Audio duration is not policy-driven.** `refine.py` targets a
  single word range (150–360). Not tiered by story complexity.
- **No player queue.** `Feed.tsx:544-619` shows a single-track floating
  player. No "next", no "play new since last check", no per-category
  queue.
- **Blogs summary is behind a click.** `Blogs.tsx:159-207` — card shows
  only kicker + title + meta. `summary_short` hook appears only after
  expansion. User must judge each blog by title alone.

**Not observed / already reasonable:**

- The 8-cat taxonomy exists and is coherent. Legacy `category` field is
  kept alongside `main` / `sub` (`Feed.tsx:53-73`) — good back-compat.
- Sub-strip chips render only when the active category has non-zero sub
  counts (`Feed.tsx:377-416`) — good.
- LIVE dot exists for Sports > Major Events with a 24h window
  (`Feed.tsx:271-286`) — a genuinely restrained use of the accent.

---

## 2. What should remain unchanged (and why)

- **The 8-cat top-level taxonomy** — `AI, TECH, SCIENCE, SPORTS, US,
  INDIA, WORLD, BUSINESS`. Already locked in PLAN.md, matches persona,
  used across the codebase. No net gain from expanding.
- **The refine pipeline (6 layers).** The layers exist as calcified bug
  fixes; each solved a specific TTS or hallucination failure. Do not
  collapse without an A/B.
- **Kokoro-ONNX + `normalize.py` + Whisper round-trip.** Explicitly
  preserved per the critique. Deterministic, zero-cost, portable.
- **`sources.yaml` + `blogs.yaml` structure.** Tier A/B/C model is
  sound. Sources being added is a separate exercise.
- **The editorial print aesthetic.** Single vermilion accent, light
  theme only, no AI-slop chrome. No usability problem identified.
- **`data/rejections/*.jsonl` audit log.** The only way we currently
  observe filter behavior. Keep it.
- **The LIVE dot pattern for Sports → Major Events.** Restrained,
  earned use of the accent. Extend, don't replace.
- **The static-JSON-in-git architecture** for the manifest itself.
  The audio binary issue (§13) is separate; the JSON approach is fine.

---

## 3. Persona / product mismatches

The current product is optimised for **browsing an archive**. The
re-anchored persona wants a **change-detection tool with progressive
depth**. The concrete mismatches:

| Signal today | What the persona wants |
| --- | --- |
| Hero says "106 stories · 175 min" — feels like a queue. | "8 meaningful changes since your morning briefing." |
| Chronological grid, all days flat. | Hierarchy: what's new since last check → worth knowing → beat views → archive. |
| Every day-group shows its own "N°01 / Today". | Exactly one "lede of the day" for the current day. |
| One-size summary length. | Length by information density — 45s for a result, 3 min for a policy change. |
| MiniLM dedup drops same-event follow-ups. | Same-event new-development retained + attached to a cluster. |
| T1 penalises non-actionable news. | Informational significance is valued; only *manufactured* engagement is penalised. |
| No "you're caught up" state. | Explicit completion signal so the session ends. |
| `read` vs `article ↗` — two clicks, unclear roles. | `Read brief` (in-app) vs `Original article ↗` (external). |
| "Refined by hand" copy. | Truthful — this is automated editorial. |
| Blog cards are title-only until expanded. | 2–3 line "why this is worth your time" hook visible on the card. |

These are all correctable **without expanding the taxonomy, replacing
the TTS engine, or introducing new infrastructure**.

---

## 4. Proposed information architecture

Replace the flat chronological grid with the following hierarchy on
the news page. Section names and thresholds are illustrative and will
be tuned against real feed distributions.

```
──────────────────────────────────────────────────────────────
  BRIEFING · Sun 14 Sep 2026            [ New since your last check ]
──────────────────────────────────────────────────────────────

  CATCH UP                                            (P0)
  ────────
  The 3–8 most meaningful new stories since the user's last
  visit. Set size is data-driven, not fixed. Chosen by:
  significance_v2 score, persona-relevance boost, and
  novelty vs event cluster. One story per event cluster.

  WORTH KNOWING                                       (P1)
  ─────────────
  Relevant secondary developments since the last visit,
  ordered by significance. Persona-relevance and India /
  sports weightings apply. One card per event cluster.

  YOUR BEATS                                          (P0)
  ──────────
  Existing 8-cat tuner: AI · Tech · Science · Sports · US ·
  India · World · Business. Same sub-strip. Same filtering.
  This is the "expand into a category" surface.

  EXPLORE / ALL                                       (P1)
  ─────────────
  Full accepted corpus for the current day. Chronological.
  Includes stories not surfaced above.

  ARCHIVE                                             (P2)
  ───────
  Prior days, collapsed by day header. Same card model.
──────────────────────────────────────────────────────────────
  You're caught up.                                   (P0)
  ─── Next fire at 19:00 UTC ───
```

**State model (browser-local only, single-user product):**

- `lastVisitAt` (ISO): set on page load, persisted to `localStorage`.
- `completed[storyId]`: set when a story's audio ends or the user
  expands the brief for >15s. Persisted to `localStorage`.
- No server state, no auth, no cookies.

**"CATCH UP" set-selection algorithm (P0, but simple):**

```
new_since = stories where created_at_ts > lastVisitAt
                and story is not in completed[]
                and story is the top-ranked in its event cluster

score = significance_v2.score
      + persona_boost (India +0.15, sports:priority-list +0.10,
                       AI +0.05, tech-cybersec +0.10)
      + cluster_freshness_bonus (new_development in known cluster +0.05)

catch_up = top-N by score where score >= 0.65, N in [3, 8]
worth_knowing = next tier by score where score in [0.40, 0.65)
```

If `new_since` is empty, `CATCH UP` renders as:

```
You're caught up. Next fire at 19:00 UTC.
```

No 106-story queue framing.

**Hero replacement (P0):**

- Before: `106 stories · 175 min listen · 12 sources`
- After: `8 meaningful changes since your morning briefing · 11 min listen`
  Falls back to `Nothing new since your morning briefing. You're caught
  up.` when empty.

**Truthful copy fix (P0):**

- `refined by hand, read aloud in a minute or two` → `refined for
  spoken audio, read aloud in one to four minutes.`

---

## 5. Collapsed / expanded story structure

Three levels — progressive disclosure. Level 1 is the card, Level 2 is
the expanded brief, Level 3 is a deeper view (only for stories that
warrant it).

### LEVEL 1 — SCAN (card, always visible)

```
┌────────────────────────────────────────────────────┐
│ [cover]  AI · Policy & Safety     ●LIVE   1:42     │
│          10:32 UTC · 3 sources                     │
│                                                    │
│ India CERT-In issues advisory on Windows           │
│ zero-day exploited in the wild                     │
│                                                    │
│ What changed: New CERT-In advisory names three     │  ← "what changed"
│ CVEs, urges immediate patching for enterprises     │     one-liner
│ running Windows 10 / 11.                           │     (12–24 words,
│                                                    │      from refine)
│ moneycontrol.com · Read brief · Original ↗         │
└────────────────────────────────────────────────────┘
```

**New content on the card:**

- **"What changed" one-liner** — 12–24 word plain-text extracted from
  the refined summary. Enables scan without expansion. Uses the existing
  `stakes` field (rename in UI to "what changed" — same field).
- **Source count** shown always, not only when > 1.
- **Kicker separator** — `MAIN · SUB` with a middle dot, category as
  the identity, sub as a de-emphasised chip.

**Actions on the card:**

- `Read brief` — expands Level 2 in place (renames current `read`).
- `Original ↗` — opens publisher article (renames current `article ↗`).

**Visual state:**

- Completed stories: 70 % opacity, no colour change, no strikethrough.
  Cover greyscaled. Restores full opacity if audio is replayed.
- Age dim: keep existing >18h / >48h bucketing.

### LEVEL 2 — BRIEF (expanded in place)

Uses the existing `summary` field from `refine.py`. No new LLM call.
Content preserves:

- important names, numbers, dates, decisions, results, policy changes,
  technical capability changes, relevant context, known consequences.

Add above the brief body:

```
WHY THIS MATTERS
────────────────
<12–28 word stakes line from refine layer 2a>

WHAT CHANGED
────────────
<12–24 word plain-language change one-liner (same field
 shown at Level 1 — repeat is intentional; the card is a scan,
 the brief is a re-anchor)>
```

Add below the brief body:

```
CONTEXT              (only if depth is available for this story)
─────────
• Prior development: <headline of matching same-cluster earlier story>
• Prior development: <…>
Read the timeline ↓                    ← opens Level 3

SOURCES
───────
reuters.com · moneycontrol.com · thehindu.com    ← from sources[]

Original article ↗
```

### LEVEL 3 — DEPTH (only for cluster stories)

Renders only when `event_id` is set and the cluster has ≥ 2 entries:

- Event timeline (all cluster entries, chronological, one line each).
- Any multi-source hydration outputs.
- Direct links to every source article, not just the primary.

This is a UI surface; no new pipeline layer.

**No new LLM calls at Level 2 or Level 3.** Everything reuses fields
already produced by `refine.py`.

---

## 6. Minimum orthogonal metadata schema

The critique proposes a rich orthogonal metadata vocabulary. The
minimum useful subset for the current product, not the entire wish list:

```jsonc
{
  // Already present — do not touch.
  "main": "SPORTS",
  "sub": "Badminton",
  "location": { "name": "Paris", "country": "France", "lat": 48.85, "lng": 2.35 },

  // New — required (P0 unless noted).
  "topics": ["cybersecurity", "windows", "cert-in"],   // free-form, LLM
  "entities": ["Microsoft", "CERT-In", "Government of India"],
  "regions": ["IN", "GLOBAL"],                          // ISO country codes + GLOBAL
  "story_type": "REGULATORY_ADVISORY",                  // enum, see below
  "impact_scope": "NATIONAL",                           // GLOBAL | REGIONAL | NATIONAL | LOCAL | SECTOR | NICHE
  "importance": "MAJOR",                                // MAJOR | NOTABLE | ROUTINE
  "persona_relevance": {                                // 0–1 floats, LLM-derived
    "india": 0.9,
    "technology": 0.85,
    "business": 0.2
  },

  // Sports-only (P0 for sports coverage quality).
  "sport": "BADMINTON",
  "competition": "BWF_WORLD_CHAMPIONSHIPS",
  "competition_stage": "FINAL",
  "athletes_or_teams": ["PV Sindhu", "An Se-young"],

  // Event clustering — see §7 (P0).
  "event_id": "evt-2026-09-bwf-worlds",
  "event_update_type": "RESULT"                         // ANNOUNCEMENT | UPDATE | RESULT | RESOLUTION
}
```

**`story_type` enum (initial set, extensible):**

```
ANNOUNCEMENT · UPDATE · RESULT · RESOLUTION · DISCOVERY ·
REGULATORY_ADVISORY · POLICY_CHANGE · POLICY_PROPOSAL ·
INCIDENT · SECURITY_VULNERABILITY · DEAL_M_A · EARNINGS ·
LAUNCH · APPOINTMENT · OBITUARY · CEREMONY · OPINION
```

Where possible, `story_type` is a **categorization prompt output**
(one extra field on the existing Gemini call, no additional call).
`impact_scope` and `importance` are also single-call outputs.

**All new fields are additive.** Legacy stories without them are
treated as `importance: NOTABLE`, `impact_scope: SECTOR`, all lists
empty, `persona_relevance` derived from `main`.

**What this unlocks:**

- Sports relevance (§9) reads `sport` + `competition` + `importance`,
  not headline keywords.
- CATCH UP scoring (§4) reads `importance` + `impact_scope` +
  `persona_relevance`.
- India relevance boost reads `regions.includes("IN")` OR
  `persona_relevance.india > 0.6`.
- Event clustering (§7) reads `event_id`.

---

## 7. Event-aware deduplication

Current `dedup.py` is drop-only. Proposal keeps MiniLM as first stage
and adds a light second stage — **no vector DB, no external services**.

### Stage 1 — candidate pairing (existing)

MiniLM cosine ≥ 0.82 against last-3-days + in-batch. Unchanged. Now
outputs *candidate pairs* rather than "drop".

### Stage 2 — event/development classifier

For each candidate pair, decide one of:

- **`SAME_EVENT_SAME_DEV`** — same underlying event, same development,
  different source. → Merge: keep the higher-tier source's article,
  append the lower-tier to `sources[]`, drop the second entry.
- **`SAME_EVENT_NEW_DEV`** — same underlying event, meaningful new
  development. → Both retained. Both share `event_id`. Newer story's
  `event_update_type` set (`UPDATE` / `RESULT` / `RESOLUTION`).
- **`DIFFERENT_EVENT`** — coincidental similarity. → Both retained.
  No `event_id` link.

Classifier is a **single Gemini call per pair** (batched by run,
temperature 0.0). Prompt inputs: title + first ~200 words of each
article + published_at + entities.

**Complexity control:**

- Only pairs that pass MiniLM ≥ 0.82 hit Stage 2 (typically < 20 pairs
  per run at current volume).
- `event_id` is deterministic — e.g., a hash of the *first* story's
  `entities` + first-observed date. Not persistent across long time
  windows.
- Cluster staleness: clusters with no new stories for 30 days expire
  from the active cluster table. Cluster IDs on existing stories are
  frozen and remain queryable.

### Cluster table

`data/clusters.json`:

```jsonc
{
  "clusters": [
    {
      "id": "evt-2026-09-bwf-worlds",
      "created_at": "2026-09-10T…",
      "last_seen_at": "2026-09-14T…",
      "title": "BWF World Championships 2026",
      "entities": ["BWF", "PV Sindhu", "An Se-young"],
      "story_ids": ["…", "…", "…"]
    }
  ]
}
```

### Test cases (all P0 to have coded before shipping)

| # | Input | Expected outcome |
| --- | --- | --- |
| T1 | Reuters + BBC report the same Fed rate decision | Merge. Higher-tier source wins. `sources[]` gets both. |
| T2 | "India reaches badminton semifinal" → "final" → "wins championship" | Three stories retained, all share `event_id`. `event_update_type` = UPDATE, UPDATE, RESULT. |
| T3 | "Draft privacy bill proposed" → "Bill passed" → "Implementation date announced" | Three retained, one cluster, types = ANNOUNCEMENT, POLICY_CHANGE, UPDATE. |
| T4 | "Acquisition announced" → "Regulator challenges acquisition" → "Acquisition closes" | Three retained, one cluster, types = DEAL_M_A, UPDATE, RESOLUTION. |
| T5 | Company product launch on Monday + unrelated security CVE in the same product on Friday | Different clusters. Both retained. |
| T6 | Ongoing geopolitical conflict — daily "shelling continues, X casualties" reports with no meaningful state change | First one becomes the cluster anchor. Subsequent ones are `SAME_EVENT_SAME_DEV` and get merged (append to `sources[]`) rather than each surfacing as a card. |
| T7 | Two outlets summarise the same OpenAI blog post | Merge. OpenAI blog is the primary source; both outlets appended. |
| T8 | HN link to a paper + Ars Technica article about the same paper | Merge. Both appended. |

---

## 8. Significance change proposal

**Problem:** T1 penalises stories without a direct reader action. This
is wrong for the persona — the persona reads *to understand*, not to
act.

**Proposal:** replace T1 with an **informational significance** vector
that separates the concerns the critique names.

### Remove

- **T1** (actionability penalty) — deleted entirely.

### Keep

- **T2** (novelty) — routine repeats of the same beat still get a
  penalty. Now cluster-aware: `SAME_EVENT_SAME_DEV` recurrence gets
  −0.2, `SAME_EVENT_NEW_DEV` does not.
- **T3** (substance-over-signalling) — MoUs, aspirational targets,
  "committee formed to consider…" still get −0.3.

### Add

Four independent signals, each 0.0–1.0, all inputs to a single
weighted score. No LLM call added — these come out of the existing
categorization + refine outputs, plus one new pass on the refine call.

```
consequence         (would knowing this materially affect the reader's
                     understanding of their industry / country / world?)

novelty_of_fact     (is this a new fact, or a recycled framing of a
                     previously known fact?)

scale_of_impact     (how many people / how much capital / how much
                     ground does this move?)

lasting_importance  (will this still be relevant in 6 months?
                     Regulations, records, treaties, breakthroughs → yes.
                     Daily market moves, minor product updates → no.)
```

Final `score` becomes:

```
score = 0.35 * consequence
      + 0.20 * novelty_of_fact
      + 0.20 * scale_of_impact
      + 0.15 * lasting_importance
      + 0.10 * persona_relevance_max   // max of the persona_relevance fields
      - 0.20 * T2_recurrence
      - 0.30 * T3_signalling
```

Bands remain: `accept ≥ 0.55` (relaxed from 0.65), `borderline
0.30–0.55`, `reject ≤ 0.15`. Threshold relaxed because the removal of
T1 will pull average scores down for informational-only stories.

### Test cases (P0)

| Story | Under old v2 | Under new | Verdict |
| --- | --- | --- | --- |
| Indian runner breaks national 10 km record | Score 0.48 (T1 hit) → borderline | consequence 0.6 · novelty 0.9 · scale 0.5 · lasting 0.7 · persona 0.8 → 0.65 | Accept |
| Physicist publishes major cosmology result | Similar T1 hit | consequence 0.7 · novelty 0.85 · scale 0.4 · lasting 0.9 · persona 0.55 → 0.66 | Accept |
| PV Sindhu wins BWF World Championship final | Score 0.5 (T1 hit) | 0.75 | Accept |
| Major geopolitical alliance shifts | Same | 0.72 | Accept |
| Amazon $8bn acquisition closes | Score 0.7 | 0.71 | Accept |
| Local college holds Ganesh Chaturthi celebration | R1 hit | R1 hit (unchanged) | Reject |
| Bollywood couple spotted at airport | R3 hit | R3 hit | Reject |
| "Government to consider forming committee on AI regulation" | T3 hit | T3 hit | Demote |
| "Shelling continues in region X, no casualty change from yesterday" | Would pass v2 | Cluster-aware T2 recurrence → demote | Demote to WORTH KNOWING or drop |
| SaaS company Series B raise, no product change | Passes v2 | consequence 0.2 · novelty 0.3 · scale 0.15 · lasting 0.15 · persona 0.3 → 0.25 | Reject |

### Regression guard (P0)

Before merging: run new scorer against the last 30 days of manifests +
rejections log. Reject if:

- Accept rate drops > 30 % on any single day, OR
- Any of the 10 above test-case verdicts differs from expected, OR
- The "informational classic" test set (records, discoveries, results)
  loses > 10 % of previously-accepted entries.

---

## 9. Sports relevance design

**Problem:** current SPORTS coverage is broad-source and headline-keyword
driven. Persona weights badminton, athletics, road running, marathons,
cricket, F1, Indian sporting achievements, and Olympics / Asian Games /
Commonwealth Games / world championships. Currently these are indistinguishable
from generic NBA / MLB / soccer output.

**Proposal:** don't hard-whitelist. Use orthogonal metadata (§6) plus a
sport-specific scoring adjustment inside significance.

```
sport_priority = {
  BADMINTON: 1.0,
  TRACK_AND_FIELD: 1.0,
  ROAD_RUNNING: 1.0,
  MARATHON: 1.0,
  CRICKET: 0.95,
  FORMULA_1: 0.9,
  TENNIS: 0.7,
  CYCLING: 0.7,
  BOXING_MMA: 0.6,
  SOCCER: 0.5,
  BASKETBALL: 0.4,
  GOLF: 0.35,
  BASEBALL: 0.3,
  NFL: 0.3,
  RUGBY: 0.35,
  HOCKEY: 0.3,
  OTHER: 0.3
}

competition_priority = {
  OLYMPICS: 1.0, ASIAN_GAMES: 0.95, COMMONWEALTH_GAMES: 0.9,
  WORLD_CHAMPIONSHIPS: 0.95,
  MAJOR_INTERNATIONAL: 0.7,
  DOMESTIC_TOP_TIER: 0.5,
  REGULAR_SEASON: 0.3
}

sports_score_boost =
    (0.4 * sport_priority[s.sport])
  + (0.3 * competition_priority[s.competition])
  + (0.2 * (s.athletes_or_teams contains an Indian → 1.0 else 0.0))
  + (0.1 * (s.importance == MAJOR ? 1.0 : 0.4))
```

Applied inside significance as a **replacement of `persona_relevance`
when `main == SPORTS`**. Not additive on top — this *is* the persona
relevance for sports.

**Override — global event.** If `competition_priority ≥ 0.9` OR
`importance == MAJOR` AND `impact_scope == GLOBAL`, boost bypasses the
sport whitelist. So a global-scale NFL story (e.g. league-wide policy
change with broader implications) can still surface.

**Test cases (P0):**

- PV Sindhu wins BWF World Championships final → 0.4·1.0 + 0.3·0.95 +
  0.2·1.0 + 0.1·1.0 = **0.885** → surfaces.
- Regular-season NBA game result → 0.4·0.4 + 0.3·0.3 + 0.2·0 + 0.1·0.4
  = **0.29** → does not surface.
- Neeraj Chopra breaks world javelin record → 0.4·1.0 + 0.3·0.7 +
  0.2·1.0 + 0.1·1.0 = **0.81** → surfaces.
- Boston Marathon winner → 0.4·1.0 + 0.3·0.9 + 0.2·0 + 0.1·1.0 =
  **0.77** → surfaces.
- Ballon d'Or announcement → 0.4·0.5 + 0.3·0.7 + 0.2·0 + 0.1·1.0 =
  **0.51** → surfaces (borderline; global event override may lift).

---

## 10. Audio-duration policy

**Problem:** all news stories currently target 150–360 words → ~60–120 s
of audio. Both a market open and a major regulatory change get the
same envelope.

**Proposal — length by information density.** Introduce a
`length_tier` on refine driven by `story_type` + `importance` +
`impact_scope`:

| Tier | Word range | Audio | Trigger |
| --- | --- | --- | --- |
| **BRIEF** | 90–180 w | 45–75 s | RESULT, EARNINGS, ROUTINE UPDATE, single-fact story |
| **STANDARD** | 180–360 w | 75–150 s | Most stories. Current default. |
| **DEEP** | 400–700 w | 150–240 s | `importance: MAJOR` AND (`impact_scope: NATIONAL` OR `GLOBAL`). Policy changes, regulatory advisories, treaties, major discoveries. |
| **FEATURE** | 700–1100 w | 240–360 s | Rare. Only for stories where the persona would otherwise open the article — reserved judgment call by the LLM, requires structured justification. |

Blog LONG stays at 600–1500 w / 3–8+ min. Unchanged.

**Rules:**

- Length tier is decided **before** the DRAFT prompt runs. Prompt
  variant per tier — `DRAFT_BRIEF`, `DRAFT_STANDARD`, `DRAFT_DEEP`,
  `DRAFT_FEATURE`. Each has explicit padding guidance and structure
  requirements.
- No two-variant emission — one audio per story (see §11 rationale).
- Sanity check layer rejects "padded" output: if a DEEP story's
  actual information density (unique named entities + numbers + dates
  per 100 words) is below the STANDARD threshold, downgrade the tier
  and re-refine.

**What DEEP requires the prompt to cover explicitly:**

```
- what changed
- what existed before
- who is affected
- the important requirements or details
- why it matters (stakes)
- what happens next
```

If the DRAFT can't fill all six from the source, it's not a DEEP
story — downgrade to STANDARD.

---

## 11. Audio player / queue UX

Preserve the current single-track floating player. Add a queue that
composes existing per-story MP3s — **no server-side stitching, no new
"combined" audio file**.

### Queue affordances (P0 marked)

- **`Play catch-up`** — enqueue everything in the CATCH UP section, in
  order. (P0)
- **`Play new since last check`** — same as catch-up when new_since is
  non-empty; otherwise disabled. (P0)
- **`Play <category>`** — enqueue current filtered view. (P1)
- **`Play India`**, **`Play AI + Tech`**, **`Play Sports`** — preset
  queue buttons pinned to the player. (P1)
- **Next / previous** buttons in the player. (P0)
- **Client playback speed** — 0.9× / 1.0× / 1.1× / 1.25× / 1.5×.
  Client-side only; TTS output stays at 1.08× baseline. (P1)
- **Queue drawer** — list of upcoming items, drag to reorder, tap to
  jump. (P2)
- **Persist queue across refresh** — `localStorage`. (P1)

### Behaviour

- Playing a story marks it `completed` when its audio ends (not just
  when the queue advances).
- Completed stories are visually dimmed (§5) but stay in the queue if
  the user has manually queued them.
- Auto-advance to next in queue on `onEnded`. If the queue is empty,
  show "You're caught up. Next fire at HH:MM UTC."
- ESC still closes the player. Player close does not clear the queue.

### Explicit non-goals

- No combined "one big MP3" file. Per-story files stay canonical.
- No client-side crossfade or mixing (adds complexity for zero user
  benefit).
- No server-recorded per-user listening history (single-user product,
  local state is enough).

---

## 12. Blogs UX

Current state (from §1): card shows only kicker + title + meta;
`summary_short` is behind expansion. User cannot triage.

### Changes

- **Always-visible 2–3 line hook** (P0). Rename `summary_short` in UI
  to **"Why this is worth your time"**. Rendered under the title on
  the card, before the meta row. No expansion required.
- **`Listen` button on card** (P1). Currently listen is inside the
  expanded body. Move to the card so it's actionable from scan.
- **`Recommended this week` strip** (P1). A small horizontal shelf at
  the top of `/blogs` showing 3 entries by rotation-freshness × topic
  balance × source diversity. Not a ranked feed — a curated shelf that
  changes weekly.
- **Topic chips inline on card** (P2). Currently at the bottom of the
  expanded body.

### Preserved

- Retention arc-clock (30-day per entry).
- Source · author · reading time · audio duration meta.
- Expandable full long summary + `Continue at <source> ↗` at bottom.
- Sort tabs (Freshest / By source).
- Empty state plate.

---

## 13. Data migration & backward compatibility

**Manifest schema is additive.** Existing stories without new fields
are treated as:

- `importance: NOTABLE`
- `impact_scope: SECTOR`
- `regions: []` (inferred from `location.country` if present)
- `topics: []`
- `entities: []` (populated by a one-time backfill pass — see below)
- `persona_relevance: derived from main` (heuristic map)
- `event_id: null`
- `event_update_type: null`
- `length_tier: STANDARD`
- `story_type: null` (falls back to `main`/`sub`-driven default)
- Sports fields absent unless `main == SPORTS`.

**Backfill (one-time, offline, P1):**

- Run a `pipeline.backfill_metadata` script that re-invokes the
  categorization prompt with the new fields, only on stories in the
  current 7-day retention window. Writes fields in place. Skips
  audio + refine — cheap.

**Frontend forward compatibility:**

- `Feed.tsx` continues reading `main`/`sub`/`category`/`subcategory`
  as it does today. New fields (`importance`, `event_id`, etc.) are
  read defensively (`?? default`). Legacy stories keep rendering.

**Nothing in `sources.yaml`, `blogs.yaml`, `refine.py`, `tts.py`, or
`normalize.py` changes.**

---

## 14. Files that would likely require modification

Only listed to show scope. Nothing is edited in this design phase.

**Pipeline (new fields, new logic):**

- `pipeline/categorize.py` — add `topics`, `entities`, `regions`,
  `story_type`, `impact_scope`, `importance`, `persona_relevance`.
  Sports fields when `main == SPORTS`.
- `pipeline/significance.py` — remove T1, add consequence / novelty /
  scale / lasting / persona weighted score. Update band thresholds.
- `pipeline/dedup.py` — split into `dedup.py` (Stage 1, existing) and
  new `cluster.py` (Stage 2 event/development classifier + cluster
  table read/write).
- `pipeline/refine.py` — add `length_tier` up front, four DRAFT prompt
  variants, sanity check for density.
- `pipeline/manifest.py` — persist new fields, cluster table
  reference.
- `pipeline/run.py` — wire cluster step in.
- **New:** `pipeline/backfill_metadata.py` (one-time).
- **New:** `data/clusters.json` (managed).

**Frontend:**

- `site/src/pages/index.astro` — hero copy change, sectioned IA,
  removal of `refined by hand`. Reads `lastVisitAt` via a small client
  script.
- `site/src/components/Feed.tsx` — new sections (CATCH UP / WORTH
  KNOWING / YOUR BEATS / EXPLORE / ARCHIVE), completed-state
  handling, queue affordances, "what changed" line on card, `Read
  brief` / `Original ↗` copy fix, "You're caught up" state, next /
  prev / speed controls.
- `site/src/components/Blogs.tsx` — always-visible hook, listen on
  card, recommended-this-week shelf.
- `site/src/styles/global.css` — completed-state dim, section
  dividers, "You're caught up" plate, queue drawer.

**Not modified:**

- `pipeline/normalize.py`, `pipeline/tts.py`,
  `pipeline/audio_validate.py` — audio stack preserved as-is.
- `sources.yaml`, `blogs.yaml` — no source changes.
- The 8-cat taxonomy — locked.

---

## 15. Test cases

Consolidated from the section-level cases above. Should exist as
`pipeline/tests/*.py` (or similar) *before* the corresponding change
ships. Currently we have no unit test infrastructure — this work
proposes we add a minimal one.

**Metadata (§6):**

- M1 — Story with `main: SPORTS`, `sub: Badminton` → `sport:
  BADMINTON` populated by categorize prompt.
- M2 — Indian regulator advisory → `regions` includes `"IN"`,
  `story_type: REGULATORY_ADVISORY`.
- M3 — SaaS Series B → `story_type: DEAL_M_A`, `impact_scope: SECTOR`,
  `importance: ROUTINE`.

**Dedup / clustering (§7):**

- T1–T8 from §7 above. All must pass before Stage 2 is enabled.

**Significance (§8):**

- 10 test-case rows from §8 table. Verified expected verdicts.

**Sports (§9):**

- The five sport-score examples from §9.

**Audio (§10):**

- Same story regenerated across all four tiers. Density check catches
  padded DEEP output.
- Whisper WER remains < 0.10 across all tiers (no regression from
  the change in target length).

**Frontend:**

- CATCH UP set-selection produces same result for two consecutive
  loads if nothing new arrives (idempotence).
- `You're caught up` state renders when `new_since` is empty.
- Completed story dims after audio ends; restores after re-play.
- Queue survives page refresh.
- `Read brief` opens Level 2; `Original ↗` opens external tab.

---

## 16. Browser validation criteria

Manual + Playwright. To be validated on `briefing-psi-ten.vercel.app`
preview before promoting to prod.

1. Hero shows change-based framing, never "N stories · N min".
2. First-visit user (no `lastVisitAt`) sees a sensible default —
   e.g. "top developments in the last 24 hours" — not an empty state.
3. "N°01 / Today" appears exactly once, on the current day's CATCH UP
   first card.
4. Historical days in ARCHIVE do not display "N°01 / Today".
5. Every card carries a "what changed" one-liner.
6. `Read brief` and `Original ↗` are visually distinct and behave as
   labelled.
7. Completed cards render at 70 % opacity, cover greyscaled.
8. `You're caught up` plate appears when new_since is empty.
9. `Play new since last check` disabled when new_since is empty,
   enabled otherwise.
10. Queue drawer opens; drag-reorder works; next/prev cycle through it.
11. Speed control at 1.25× actually plays at 1.25× (verify with
    `audio.playbackRate`).
12. `Recommended this week` shelf on `/blogs` shows exactly 3 entries.
13. Every blog card shows the "why this is worth your time" hook
    without expansion.
14. `refined by hand` copy is gone site-wide.
15. Category tuner still works exactly as today (no regression on
    filtering / sub-strip).
16. Globe view still opens from the toggle (no regression).
17. Lighthouse: LCP < 2.5 s, CLS < 0.1, TBT < 300 ms unchanged.

---

## 17. Risks, regressions, unknowns

### Risks

- **Filter drift from T1 removal.** Even with the guard in §8, real
  distributions may surprise us. Mitigation: shadow-mode the new
  scorer for one week — write both v2 and v3 scores to the manifest,
  render only v2 in UI, diff the two in a small dashboard file.
- **Cluster classifier costs.** Stage 2 adds Gemini calls per
  candidate pair. At current 106-story feed, ~10–20 pairs per run,
  ~30–60 extra calls/day. Cost impact is negligible; latency impact
  is ~30 s per run. Acceptable.
- **CATCH UP set size going to zero on quiet days.** The persona
  wants "caught up" as a signal, not a bug. Explicitly render the
  caught-up state — do not fall back to filling with older stories.
- **Completed-state losing user's place.** If localStorage is wiped
  (private tab, browser reset), the user re-sees all their reads.
  Acceptable for a single-user product; do not add server persistence
  to solve it.
- **Persona-relevance boosts becoming echo chambers.** Boosting India +
  AI + selected sports risks under-surfacing meaningful WORLD /
  BUSINESS stories. Explicit floor: WORLD and BUSINESS each guaranteed
  at least one slot in CATCH UP when a candidate exists with
  `score ≥ 0.55`.

### Regressions to guard against

- Whisper WER > 0.10 on new length tiers.
- Story count in feed drops > 30 % post-significance-change (the
  regression guard rejects this).
- Sub-strip filtering breaks (currently correct — do not regress).
- Globe view breaks (currently correct — do not regress).
- LIVE dot behaviour changes (currently correct — extend, don't rewrite).

### Unknowns

- Whether Gemini reliably produces `persona_relevance` floats without
  drifting. Needs prompt tuning + validation set.
- Whether an event-classifier prompt at 200-word article snippets is
  accurate enough. May need to bump to 400 words for policy stories.
- Whether "informational classic" test set exists — we may need to
  hand-curate 30–50 stories as a golden set before the significance
  change ships.
- Whether the browser's `localStorage` is a viable single source of
  truth for `completed[]` when the manifest changes IDs (e.g. after
  a reprune). Need an ID-stability policy.

---

## 18. Recommended implementation order

Order minimises risk and delivers user-visible value in each step.

**Phase 0 — foundation (P0, no user-visible change):**

1. Golden test set — hand-curate 30–50 stories with expected verdicts
   for significance + clustering.
2. Minimal test harness under `pipeline/tests/`.

**Phase 1 — orthogonal metadata (P0, plumbing only):**

3. Extend categorize prompt to emit `topics`, `entities`, `regions`,
   `story_type`, `impact_scope`, `importance`, `persona_relevance`.
   Sports fields conditional.
4. Manifest additive persistence + Feed.tsx defensive read.
5. Backfill script over the 7-day window.

**Phase 2 — significance rebuild (P0, gated on regression guard):**

6. Add new scorer alongside v2 (shadow mode). Diff for 3 runs.
7. Flip scorer over. Keep both scores in manifest for one week.
8. Remove v2 scorer once new scorer is stable.

**Phase 3 — event clustering (P0):**

9. Stage 2 classifier + cluster table.
10. `event_id` / `event_update_type` on stories.
11. Enrichment (merge same-event-same-dev) — reuses PLAN C4 work.

**Phase 4 — audio duration policy (P1):**

12. Four DRAFT prompt variants + tier selector.
13. Density sanity check.
14. Whisper regression run over one week of stories.

**Phase 5 — IA + progressive disclosure (P0, user-visible):**

15. Hero copy fix + `refined by hand` fix. (Trivial, ship immediately
    if desired.)
16. Sectioned feed (CATCH UP / WORTH KNOWING / YOUR BEATS / EXPLORE
    / ARCHIVE). `lastVisitAt` + `completed[]` in localStorage.
17. "What changed" line on card. `Read brief` / `Original ↗` copy
    fix. Completed dim.
18. "You're caught up" plate.

**Phase 6 — player queue (P0/P1 mix):**

19. Next / prev / queue drawer / playback speed.
20. `Play catch-up`, `Play new since last check`, per-category presets.
21. Queue persistence.

**Phase 7 — blogs (P0/P1 mix):**

22. Always-visible hook. Listen-on-card.
23. Recommended this week shelf.

**Phase 8 — sports polish (P1):**

24. Sport / competition scoring in significance.
25. Global-event override.

Nothing here proposes deleting existing functionality. Every change
is either additive (new fields, new sections) or a targeted swap
(new scorer replacing T1, prompt variant replacing single prompt).

---

## 19. Consistency review

Verifying the design against every assertion required by the brief:

| Assertion | Status | Note |
| --- | --- | --- |
| The persona is preserved | ✅ | Signal-Seeking Technical Generalist. Understanding-per-minute over content maximisation. |
| SPORTS remains first class | ✅ | Top-level category retained (§9). Sport-specific scoring boosts persona sports, does not suppress them. |
| India relevance remains important | ✅ | `persona_relevance.india` in scoring, `regions.includes("IN")` in CATCH UP boost, India kept as top-level. |
| World / current affairs are not reduced excessively | ✅ | WORLD retained as top-level. Explicit CATCH UP floor of at least one WORLD slot when a ≥ 0.55 candidate exists (§17). |
| Important negative news is not suppressed | ✅ | §8 explicitly separates informational significance from tone. Only *manufactured* engagement (T2 recurrence, T3 signalling) is penalised. Conflict + disasters + politics all pass when they represent a material change. |
| Depth is available on demand | ✅ | Level 1 → Level 2 → Level 3 in §5. Original article always reachable. |
| The full corpus remains accessible | ✅ | EXPLORE / ALL section holds the full accepted corpus. ARCHIVE holds prior days (§4). |
| No-action-required stories can still rank highly | ✅ | T1 removed (§8). Record-breaking, championship results, discoveries, alliance shifts all score high. |
| Event updates are not incorrectly deleted as duplicates | ✅ | Stage 2 classifier distinguishes SAME_EVENT_SAME_DEV (merge) from SAME_EVENT_NEW_DEV (retain, cluster). Test cases T2–T4 in §7. |
| Duplicate reporting does not create repeated cards | ✅ | SAME_EVENT_SAME_DEV → merge into higher-tier source + append `sources[]`. Test cases T1, T6–T8. |
| Audio is not padded simply to become longer | ✅ | Length tier chosen up front from `story_type` + `importance` + `impact_scope`. Density sanity check downgrades padded DEEP output (§10). |
| Existing local TTS investments are preserved | ✅ | Kokoro-ONNX + `normalize.py` + Whisper unchanged. Only DRAFT prompt tiers change. |
| Proposed UX does not turn Briefing into another infinite news feed | ✅ | CATCH UP is small and bounded (3–8). `You're caught up` state is explicit. Hero measures change, not volume. No engagement metrics anywhere. |
| No unnecessary infrastructure complexity has been introduced | ✅ | No vector DB, no event store, no queue, no server-side state. Cluster table is a single JSON file. Completed-state is localStorage. Everything else is Gemini prompt additions on the existing calls. |

**Nothing in this design proposes:**

- Replacing Kokoro with paid TTS.
- Dropping the static-JSON-in-git manifest architecture.
- Expanding the 8-cat top-level taxonomy.
- A vector DB, worker queue, or distributed event bus.
- Two audio variants per story (deferred until §13 audio-in-git problem
  is resolved, matching the brief's constraint).
- Dark mode, cosmetic redesign, or any change without a stated persona
  or bug driver.

---

**End of design review.** Awaiting approval before touching code.
