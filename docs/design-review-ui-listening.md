# Design Review — UI/UX, Information Architecture, Listening Experience

Response to the specification in `log3.txt`. **Analysis and design only —
no code modified.** Follows the 23-item required output structure in §29
of the brief. Every recommendation is classified **P0 / P1 / P2** and
connected to either the persona or a concrete design requirement.

**Relationship to prior docs.** Yesterday's `docs/design-review-2026-09-14.md`
already covered the core information hierarchy (CATCH UP / WORTH KNOWING /
YOUR BEATS / EXPLORE / ARCHIVE), three-level story structure (SCAN /
BRIEF / DEPTH), orthogonal metadata schema, event clustering, significance
rebuild, sports scoring, audio duration tiers, and player queue. **This
document does not restate that work.** It extends with what that review
did not cover:

1. Wireframe-level text diagrams at three breakpoints.
2. Mobile-specific behaviour (390 px).
3. Accessibility validation and treatment.
4. Performance implications and lazy-loading strategy.
5. Explicit browser acceptance criteria and edge-case states.

Where a section number below re-appears from the prior doc, the
treatment here is **additive detail**, not restated content.

**Limitation to be transparent about.** The brief says "open the DEPLOYED
Briefing application in a real browser… inspect it at desktop / tablet /
mobile." I have code-inspection results and produced-image screenshots
from earlier sessions, but no live-browser MCP tool wired in this
session. So this diagnosis is based on the code state I verified
yesterday (`Feed.tsx`, `Blogs.tsx`, `index.astro`, `blogs.astro`) plus
observed live behaviour from prior work. A live-browser verification
pass is listed under §23 acceptance criteria and must precede any
implementation sign-off.

---

## 1. UX diagnosis of the existing deployed application

From code + earlier live inspection:

- **Hero (`index.astro:31-42`).** Shows `{stories} · {min} listen · {sources}`.
  This is a workload framing — implies "175 minutes of homework."
- **Feed grid (`Feed.tsx:444-540`).** Chronological grid, flat across
  days. All days visually equal.
- **Day header (`Feed.tsx:447-451`).** Repeats `<day-label> · N stories`
  for every day — reinforces the backlog feel.
- **Lede cue (`Feed.tsx:462-468`).** `"N°01 / Today"` applies to
  `i === 0` of every day-group. Historical days each get their own
  "N°01 / Today" — semantically wrong.
- **Story card (`Feed.tsx:453-536`).** Displays: category kicker,
  duration, time, title, source domain, sources chip (only when > 1),
  `article ↗`, `read`. No "what changed" line. Nothing tells you what
  changed without opening.
- **`read` / `article ↗` (`Feed.tsx:509-517`).** Two different
  destinations, ambiguous labels.
- **Player (`Feed.tsx:544-619`).** Single-track floating aside.
  No queue, no next/prev, no speed control.
- **Globe (`Feed.tsx:359-374`).** Top-level view toggle, equal
  prominence with List.
- **No `completed` state.** Nothing tracks which stories the user has
  finished. `ageBucket` (lines 91-96) dims cards > 18 h and > 48 h but
  that's calendar age, not personal read-state.
- **"refined by hand" (`index.astro:44`).** Inaccurate copy — refinement
  is fully automated.
- **Blogs (`Blogs.tsx:112-209`).** Card shows only kicker + title + meta.
  `summary_short` (100–160 w hook) is only visible after expansion — you
  cannot triage the shelf.
- **Category tuner (`Feed.tsx:337-358`).** Works. Sub-strip below it
  works. LIVE-dot for Sports/Major Events works. Do not regress these.

## 2. What already works well

Explicit callout so it isn't accidentally undone during redesign.

- **Category tuner + sub-strip.** Motion `layoutId` shared-element
  transitions between category taps are pleasing and semantically
  right. Filtering is correct.
- **LIVE dot** for Sports → Major Events (`Feed.tsx:271-286`). Restrained,
  earned use of the accent colour.
- **Age dimming** via `ageBucket`. Distinguishes "today" from "> 18 h
  ago" from "> 48 h ago" without being obnoxious.
- **Editorial print aesthetic.** Single vermilion accent, light theme,
  serif lede treatment. Distinctive; **preserve**.
- **Motion is restrained.** Cards fade + rise on mount, opening the
  transcript animates `height`. No parallax, no glassmorphism, no
  "AI slop" chrome. Keep this.
- **Player** is small, non-intrusive, dismissable, ESC to close, Space
  to toggle. Good.
- **Sources chip** for stories with `> 1` source. Good pattern, needs
  extending (see §5).
- **Globe** is genuinely useful for the "what's happening where"
  question. Do not remove; just re-place (see §4).
- **Empty state plate** (`Feed.tsx:428-442`) has the right editorial
  tone. Reuse for the caught-up state.

## 3. Persona mismatches (extends 2026-09-14 §3)

Additional detail beyond the prior doc:

- **The header is loud with numbers, quiet with change.** For a
  person who did not maintain a newspaper habit, opening a page that
  says "106 stories · 175 min" is functionally a task inbox with 106
  emails. It's the primary cognitive-load producer on the current UI.
- **The feed is a single object, not a session.** There is no way to
  finish. Even after listening to five stories, the page looks
  identical. The user cannot know when to stop.
- **Every card looks equally important.** The N°01 lede treatment
  applies daily, not per-session. The visual weight of the first card
  in *today* is the same as the first card of *8 days ago*. That is
  the opposite of what "understanding per minute" wants.
- **No fast path for the four legitimate user modes.** The brief
  names four: 2 minutes, 10 minutes, driving/listening, "I want to
  understand this one deeply." Today's UI supports exactly one: browse
  by scrolling.
- **India relevance is orthogonal, but the UI treats it as a
  category.** A semiconductor policy is currently either TECH or
  INDIA. It cannot be both without duplication. This is a data-model
  gap already flagged in yesterday's review — but its UX consequence
  is that INDIA becomes a mixed dump when it should be a lens.

## 4. Proposed site information hierarchy

Refines the CATCH UP / WORTH KNOWING / YOUR BEATS / EXPLORE / ARCHIVE
structure from yesterday's §4 with specific layout decisions. Same five
zones, plus BLOGS remains a separate top-level page.

**Top-level navigation, always visible:**

```
BRIEFING          BLOGS
─────────    ─────────
[news]       [long-form]
```

**Within `/` (news), the page reads top-to-bottom in this order:**

1. **Header (persistent).** Change-based framing (§18).
2. **Session context strip.** One-line status: "New since 07:15 UTC ·
   Next fire 19:00 UTC · You're caught up." Sticky when the user scrolls.
3. **CATCH UP block** (default open). 3–8 cards.
4. **WORTH KNOWING block** (default collapsed on mobile, open on
   desktop). Header shows count and estimated listen time.
5. **YOUR BEATS.** The existing 8-cat tuner, sub-strip below it. Filter
   scope is Today by default; a toggle expands to Recent (Today + prior
   day).
6. **EXPLORE.** Chronological grid of everything in the current
   YOUR BEATS scope. Default hidden behind a "See all N accepted
   stories" link — one click away, never a wall by default.
7. **ARCHIVE.** Prior days, grouped by day header, collapsed. Each day
   has a summary line ("Fri 12 Sep · 24 stories · 21 min").
8. **Caught-up footer.** "You're caught up. Next fire 19:00 UTC."

**Globe** moves to an Explore-mode toggle (was equally prominent, now
demoted). The toggle appears next to the YOUR BEATS tuner, not at page
level. Rationale: for the "what changed?" question, the globe answers
"where did it happen?" — that's an interesting secondary question, not
the primary product.

## 5. Catch Up design

Rules that flow through into wireframes below.

- **Size is data-driven.** Between 3 and 8 cards. Selected by:
  `score ≥ 0.65` AND `story is top-ranked in its event cluster` AND
  `created_at_ts > lastVisitAt`.
- **Empty-state is a first-class outcome.** If none qualify, render:

  ```
  ─────────────────────────────────────────
   You're caught up.
   Next fire at 19:00 UTC.
   Recent stories are one tap below ↓
  ─────────────────────────────────────────
  ```

- **First-visit handling.** If `lastVisitAt` is unset (localStorage
  empty), treat as "last 24 h" so the block is not empty on first load.
- **One card per event cluster.** If a story has cluster siblings, show
  the newest development only. The Level-3 timeline surfaces the rest.
- **Single "Play catch-up" action** at the block's header:
  `▶ Play catch-up · 11 min`. Enqueues these N stories in order.
- **Persona boost is visible in ordering, not in labels.** Do not put
  "INDIA" or "AI" priority tags on the cards themselves — that would
  betray the personalisation. It should feel edited, not algorithmic.

## 6. Story SCAN design

Extends yesterday's §5 Level 1 with tight visual rules:

- **Kicker.** `MAIN · sub` with middle dot. Font: uppercase caps, tracking
  0.08em, 11 px. Colour: text tertiary. No box, no chip.
- **Title.** Serif display face, 20 px desktop / 18 px mobile, 3-line
  max with `line-clamp: 3`. Colour: text primary.
- **"What changed" line.** New. Sans, 14 px, 2-line max. This is the
  single most important addition. Populated from the `stakes` field
  produced by refine layer 2a. Prefixed by a tiny "→" glyph.
- **Meta row.** Right-aligned inline: duration · time · sources. Sources
  always visible (even at count = 1, "1 source" reads honestly). Sources
  become a chevron chip when count > 1.
- **Action row.** Left-aligned: `Read brief ▾` · `Original ↗`. Two
  distinct destinations, two distinct affordances. `Read brief` expands
  in place (chevron rotates). `Original ↗` opens a new tab.
- **Play affordance.** The cover image (or `AbstractCover`) is the play
  target on click. Hover reveals a `▶` overlay; touch shows it on the
  card corner permanently at 60 % opacity.
- **Completed treatment.** When the audio ends OR the brief has been
  expanded for > 15 s, the card is marked `completed`. Visual: opacity
  0.7, cover greyscaled. Full opacity returns on replay.
- **Cluster affordance.** If the story is in a cluster with siblings,
  show a small `· 3 developments` marker in the meta row. Tapping it
  scrolls to Level-3 timeline once the card is expanded.
- **No progress bars, badges, dot-badges, "NEW!" flags.** The change is
  communicated by the "what changed" line + placement in CATCH UP.
  Badges are visual debt.

## 7. Story BRIEF design (Level 2 — expanded)

Body flows without labels on every paragraph. Layout creates hierarchy.

```
─────────────────────────────────────────────────────────
  [Level 1 card, expanded state]
  ─────
   → What changed        <same as scan level; re-anchors>

   Why it matters        <serif italic, 14 px, 2 lines max>

   <Body paragraphs from refine.summary — 3–7 short paras.
    Serif, 16 px, 1.55 line-height. First paragraph is the
    "what happened" beat. Middle paragraphs are important
    detail / context. Last paragraph is what happens next
    when legitimately known.>

   Sources                <label; small caps, tertiary>
   ─────────
   RBI · Reuters · Unacademy IAS English  (explainer)

   [Read the original ↗]  [Watch explainer 18:30 ↗]   (present only if applicable)
─────────────────────────────────────────────────────────
```

**Rules:**

- No visible "WHAT HAPPENED / IMPORTANT DETAIL / WHY IT MATTERS / WHAT
  HAPPENS NEXT" labels. Brief §5 explicitly warns against this: "avoid
  visually labelling every paragraph if that makes the editorial
  experience mechanical." Typography + paragraph rhythm do the work.
- The italic "why it matters" line is the exception. That one label is
  earned: it is the persona's promised value.
- Sources list uses source_role suffix `(official)` / `(reporting)` /
  `(explainer)` where present. If all three are `INDEPENDENT_REPORTING`,
  omit the suffix.
- "Watch explainer" deep-link only when a YouTube segment is attached
  via the enrichment path (see YouTube design review §25).

## 8. Story DEPTH design (Level 3)

Rendered only when meaningful data exists. Three sub-blocks, any of which
may be empty:

```
─────────────────────────────────────────────────────────
  CONTEXT                              <smcaps, tertiary>
  ───────
    Prior policy: <content>            — Drishti IAS English (explainer)
    Affected groups: <content>         — Reuters (reporting)
    Implementation detail: <content>   — RBI press release (official)

  TIMELINE                             <smcaps, tertiary>
  ────────
    12 Sep · Proposed
    13 Sep · Passed              [current]
    (implementation date TBA)

  ALL SOURCES                          <smcaps, tertiary>
  ────────────
    RBI                — official     · direct
    Reuters            — reporting    · direct
    Business Standard  — reporting    · direct
    Unacademy IAS EN   — explainer    · YouTube 18:30–25:15
─────────────────────────────────────────────────────────
```

- **CONTEXT.** Populated from `enrichment_deltas[]` (YouTube design §11).
- **TIMELINE.** Only present when the story is in a cluster with ≥ 2
  entries.
- **ALL SOURCES.** Distinct source_role labels; `direct` vs deep-linked
  video timestamp.
- Depth is a **peel** — tapping "Go deeper ▾" at the end of Level 2
  reveals Depth in place. Not a separate route, not a modal.

## 9. Event-cluster UX

Two visual behaviours depending on cluster state:

- **Cluster with a new development.** The newest story appears in
  CATCH UP; earlier developments are collapsed under `· 3 developments`
  in its meta row. Timeline at Level 3 shows all developments.
- **Cluster with recurring same-development coverage** (six Reuters
  updates on the same conflict day). Do NOT show six cards. Show one
  card in WORTH KNOWING with `· 6 updates today · sources: 6`.

**Card affordance for a cluster:**

```
     BUSINESS · Regulation
  ─────────────────────────────────────────────
   RBI raises policy repo rate to 6.75 %
   → Rate hike widens fight against sticky
     inflation; two more meetings pencilled in
                                       · 3 developments
   1:42   Read brief   Original ↗   3 sources
```

The `· 3 developments` marker is the entry into the timeline.

## 10. Audio / listening UX

Extends yesterday's §11 with mobile behaviours and specific control
placement.

### 10.1 Persistent player

- **Desktop / laptop:** bottom-right floating aside, ~380 px wide.
  Vertical stack: play/pause · title · meta · scrubber · time · close.
  Waveform on the right side. Same as today, plus next/prev.
- **Tablet:** same shape, ~90 % width, bottom-centred.
- **Mobile (390 px):** full-width bottom bar, 76 px tall. Play + title +
  scrubber. Tap the bar to expand a bottom-sheet with full controls
  (queue, speed, source article, close). See §15.

### 10.2 Controls

- Play / pause (Space).
- **Previous / Next** (Left / Right arrows). Cycles through the current
  queue.
- **Scrubber** (existing).
- **Playback speed** — small `1.0×` chip that cycles `1.0× · 1.15× ·
  1.25× · 1.5×` on tap. Client-side `audio.playbackRate`. No TTS
  regeneration.
- **Queue drawer** (`Q` key on desktop, "queue" chip on mobile). Shows
  next-up cards with drag-to-reorder. Persisted to localStorage.
- **Close** (ESC / ✕). Pauses and clears the visible player; does not
  clear the queue.

### 10.3 Queue affordances

Presets, all composed from per-story files — no combined MP3:

- On the CATCH UP block header: `▶ Play catch-up · 11 min`.
- On the WORTH KNOWING block header: `▶ Add to queue · 8 more`.
- On any category tab: `▶ Play <category>` next to the tuner label.
- Explicit shortcuts pinned in the queue drawer:
  `Play new since last check` · `Play AI + Tech` · `Play India` ·
  `Play Sports`.

### 10.4 Duration honesty

- The card and player both show accurate duration BEFORE playback,
  computed from `estimated_duration_s`.
- After `onLoadedMetadata`, the real `duration` from the audio element
  replaces the estimate. Show whichever is available.
- Reading the wrong number is a small trust breach — the estimate must
  be within ±10 % of actual.

### 10.5 Content-aware length

Content-side (yesterday's §10): BRIEF / STANDARD / DEEP / FEATURE tiers.
UI-side: each card's meta row simply shows the true duration.
No visual marker for "this is a DEEP one" — the user sees "2:48" vs
"1:12" and knows.

## 11. Sports UX

Sub-navigation for the SPORTS tab (persona weights from brief §13):

```
SPORTS   [For you]  Badminton   Athletics   Cricket   F1   Major Events   Marathons   More ▾
```

- **For you** is the default sub-tab. Combines: badminton + athletics +
  road running + marathons + cricket + F1 + Indian-athlete stories.
  Backed by `sport_priority × competition_priority × indian_athlete`
  (yesterday's §9).
- **More ▾** expands to Tennis · Cycling · Boxing · Motorsport · Soccer
  · Basketball · Golf · Other.
- LIVE dot behaviour unchanged — extend to any `Major Events` currently
  running.
- No personalisation controls. The persona is fixed.

## 12. India UX

INDIA is a category **and** a lens.

- The INDIA category tab shows stories whose `main == INDIA`.
- A **cross-category India lens** — small chip near the tuner:
  `INDIA relevance ▾`. When active, filters current view to stories
  where `regions.includes("IN")` OR `persona_relevance.india ≥ 0.6`.
- Under this lens, a semiconductor policy story surfaces even though its
  `main == TECH`. No duplication.
- The default lens state is off — INDIA tab is the primary path;
  cross-category is a lens on top of any other category or ALL.

## 13. Source / provenance UX

Progressive disclosure:

- **SCAN:** one line — `moneycontrol.com · 3 sources`. Count only.
- **BRIEF:** name + role on a single line — `RBI · Reuters ·
  Unacademy IAS English (explainer)`.
- **DEPTH:** the full `ALL SOURCES` block (see §8) with roles,
  access-state, and (where applicable) video segment.

The persona should be able to answer "who says so?" without leaving the
card. Full audit trail lives in provenance metadata, not the UI.

## 14. Blog UX

Extends yesterday's §12:

- **Always-visible hook.** `summary_short` (100–160 w) renders as a
  2–3 line clamped paragraph on the card, labelled once by the
  section — no per-card `"Why this is worth your time"` label because
  that becomes editorial noise. The clamp itself communicates "there is
  more if you tap."
- **Listen button on card.** Currently inside expanded body. Move to
  the meta row next to reading-time so the user can start audio without
  expanding.
- **Recommended this week strip.** Small horizontal shelf at top of
  `/blogs`. 3 entries, chosen by: `(retention_freshness × topic_balance
  × source_diversity)`. Not a ranked feed; a curated shelf. Rotates
  weekly.
- **Retention arc-clock** (existing) is good. Preserve. No badge changes.
- **Blog player.** Same persistent player as news. Blogs simply enqueue
  their entry.

## 15. Mobile behaviour (390 px, single column)

The brief calls out mobile as the priority validation surface. Concrete
rules:

- **No horizontal overflow.** Verify at 320 px too (iPhone SE).
- **Container padding.** 20 px horizontal edge → cards fill remaining
  width. Card padding 16 px internal.
- **Header.** Reduces to `Briefing.` + change-summary. Vol. line drops.
  Section-nav becomes a segmented control below.
- **Tuner.** Horizontal scroll with snap. Sticky at top when the user
  scrolls into the feed. Reduces vertical space usage.
- **Sub-strip.** Same horizontal scroll pattern under the tuner.
- **Card grid.** Single column. Card height ≥ 160 px so touch targets
  don't crowd. Cover image aspect 16:9 at ≥ 320 px width.
- **Player.** Bottom bar 76 px, always accessible. Tap-to-expand into a
  bottom-sheet at 92 % viewport height. Handles: play/pause, prev, next,
  speed chip, scrubber, queue tab, source article, close.
- **Bottom-sheet dismiss.** Swipe down or tap outside.
- **Action row.** `Read brief` and `Original ↗` share the row but
  become 44 × 44 minimum touch targets, spaced by 12 px.
- **Level 3 (Depth).** Renders as a full-viewport peel (still same
  route). Timeline uses a vertical rail with 24 px indentation.
- **Globe.** Explore mode only. On mobile, the globe becomes a static
  map with taps to reveal stories; the 3D `react-globe.gl` is
  lazy-loaded only when explicitly requested.

## 16. State management needs

All local. No auth. No server persistence.

- `localStorage['briefing.lastVisitAt']` — ISO timestamp set on
  page load if empty; updated on session start.
- `localStorage['briefing.completed']` — `{ [storyId]: {at: ISO,
  reason: "audio_end" | "brief_expanded" } }`.
- `localStorage['briefing.queue']` — `[storyId, ...]`.
- `localStorage['briefing.speed']` — `1.0 | 1.15 | 1.25 | 1.5`.
- `localStorage['briefing.indiaLens']` — `boolean`.
- `sessionStorage['briefing.viewedInSession']` — `Set<storyId>`. Used
  for "brief-expanded > 15 s → mark completed" timer.

**Story ID stability.** For `completed[]` to survive across pipeline
reprunes, story IDs must remain stable when a story is re-refined or
re-clustered. Yesterday's design review §7 already stipulated this —
IDs are content-hash derived, cluster IDs are frozen once assigned.
This UX design assumes that constraint is honoured.

**localStorage wipe.** In private tabs or after browser reset, all
state is lost. This is acceptable for a single-user product; no server
persistence layer is proposed. The `completed` state is a nice-to-have,
not a correctness feature.

## 17. Minimal backend / data fields required

This design consumes fields from prior design reviews:

- `stakes` (refine layer 2a) — surfaces as SCAN "what changed" line.
  Already produced.
- `sources[]` with `source_role` and `access_state` — from YouTube
  design §5.1. Enables ALL SOURCES block.
- `enrichment_deltas[]` — from YouTube design §5.1. Populates CONTEXT.
- `event_id`, `event_update_type`, cluster table — from
  2026-09-14 §7. Enables TIMELINE and `· N developments`.
- `importance`, `impact_scope`, `persona_relevance` — from 2026-09-14
  §6. Drive CATCH UP scoring.

**Two small additions this design needs:**

1. **`change_line`** (new field) — the exact 12–24 word "what changed"
   sentence rendered at SCAN. It should not be extracted at render time
   from `summary` (that couples UI to LLM shape). Best: refine layer 3
   emits both `summary` and `change_line`. Fallback: `stakes`.
2. **`length_tier`** — from 2026-09-14 §10. Not shown as a badge, but
   needed for the duration honesty guard (§10.4).

**Explicitly not needed:**

- No new categories.
- No new sources fields beyond what YouTube/cluster designs already add.
- No user-preference server. State is local.

## 18. Accessibility implications

Full checklist:

- **Landmark roles.** Main content in `<main>`. Player in
  `<aside role="region" aria-label="Now playing">` (already present).
  CATCH UP / WORTH KNOWING / YOUR BEATS / EXPLORE / ARCHIVE each a
  `<section aria-labelledby>`.
- **Focus visible.** Every interactive element has a visible focus
  ring. Current design uses `outline: 2px solid var(--accent)` in
  `global.css`; preserve. Do not disable outlines on any control.
- **Keyboard navigation.**
  - Tab order top-to-bottom within cards, then between cards in reading
    order.
  - `Space` toggles play/pause on focused card OR the player.
  - `Enter` on card = expand `Read brief`.
  - `Left / Right` arrows on player = prev / next.
  - `Q` opens queue drawer on desktop.
  - `Esc` closes player / bottom-sheet.
- **Screen-reader labels.**
  - Play buttons: `aria-label="Play <title>"`.
  - Sources chip: `aria-label="Sources: reuters.com, moneycontrol.com,
    unacademy…"`.
  - Timeline events labelled with `aria-label` including date + status.
  - LIVE dot: `aria-label="Live event"` — currently uses
    `aria-label="live"`; extend.
- **Reduced motion.** Wrap all Framer/motion transitions in
  `prefers-reduced-motion` guards. NowPlayingWave already freezes at
  60 % scale under reduced-motion — extend the same rule to card mount
  animations and layout-shared transitions.
- **Contrast.** Body text on background: 7:1 (verify with a tool).
  Text tertiary on background: ≥ 4.5:1. Accent on background:
  ≥ 4.5:1. Age-dimmed cards at opacity 0.7 must still meet 4.5:1 for
  the title — validate.
- **Heading order.**
  - H1: `Briefing.` (masthead).
  - H2: section names (CATCH UP, WORTH KNOWING, …).
  - H3: day headers within ARCHIVE.
  - H4: story titles.
  - No skipped levels.
- **Link purpose.** `Original ↗` must resolve for a screen reader to
  something like `Read the original article at reuters.com`. Add
  `aria-label`.
- **Audio controls.** Player has `role="slider"` on scrubber with
  `aria-valuemin / valuemax / valuenow`. Already implemented; verify
  values update on drag.

## 19. Performance implications

Do not make the page heavier. Concrete rules:

- **Lazy-load Globe.** Already `lazy(() => import("./Globe"))`. Do NOT
  bring it into the primary bundle. Its Three.js dependency (~600 KB
  min-gz) is the single largest asset. Load only when user taps the
  Explore toggle.
- **Lazy-load blogs list markup.** `/blogs` and `/` share `motion` and
  React runtime. Split each page's specific components.
- **Do not eagerly render Level 3.** The CONTEXT / TIMELINE / ALL
  SOURCES markup should only be rendered inside an `openId === s.id
  && depthOpen` branch. Otherwise a 100-card feed pays for 100 unused
  timeline DOMs.
- **Card cover images** — already `loading="lazy"`; keep. Serve at
  displayed size (aspect 16:9 at container width). Do not ship 2000-px
  images.
- **Fonts.** Serif display face for headings; system for body if not
  already. `font-display: swap`. Preload the single serif WOFF2.
- **Audio preload.** Player element has `preload="metadata"` — keep.
  Do NOT preload the MP3 body until play is pressed.
- **Feed manifest size.** `feed.json` at ~350 KB — acceptable, but
  monitor. If it crosses 800 KB, split by day.
- **Client budget.**
  - LCP: < 2.5 s at 4G, cold cache.
  - INP: < 200 ms on card tap.
  - CLS: < 0.1.
  - JS transferred on `/`: < 220 KB gz (excluding Globe).
- **No new heavy dependencies.** No charting library, no editor
  library, no CMS SDK.

## 20. Proposed component changes

Compact list, extends yesterday's §14. All in `site/src/components/`:

- **`Feed.tsx`** — restructure return into sections. Extract:
  `<SessionStrip />`, `<CatchUp />`, `<WorthKnowing />`,
  `<YourBeats />`, `<Explore />`, `<Archive />`, `<CaughtUp />`.
  Each is a section-labeled slice of `stories`.
- **New `<StoryCard />`** — extracted from the inline `motion.article`
  inside Feed. Level 1 SCAN visual. Handles completed state, cluster
  marker, cover-play affordance.
- **New `<StoryBrief />`** — Level 2 body renderer with the italic
  "why it matters" line.
- **New `<StoryDepth />`** — Level 3 CONTEXT / TIMELINE / ALL SOURCES.
  Lazily rendered.
- **`<PersistentPlayer />`** — replaces the inline player in `Feed.tsx`.
  Owns queue, speed, prev/next. Consumed by `/` and `/blogs`.
- **New `<QueueDrawer />`** — desktop key `Q`, mobile bottom-sheet.
- **`<HeaderBar />`** — new masthead + session strip. Removes "refined
  by hand" copy.
- **`<BlogCard />`** — extracted from `Blogs.tsx`; adds always-visible
  hook + listen button on the card.
- **New `<RecommendedThisWeek />`** — small shelf at top of `/blogs`.

Styles: `site/src/styles/global.css` gains section dividers, caught-up
plate, bottom-sheet, queue-drawer, completed-state rules.

## 21. Wireframe-level text diagrams

Text mock at three breakpoints. Illustrative — final visuals inherit
current typography and vermilion accent.

### 21.1 Desktop 1440 px

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Briefing.                                                                    │
│  Vol. 01 · Sun 14 Sep 2026                             News · Blogs           │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│   8 meaningful developments since your morning briefing · 11 min listen       │
│   [ ▶ Play catch-up ]                     Last refreshed 12:03 UTC            │
│                                                                               │
├──────────────────────────────────────────────────────────────────────────────┤
│  CATCH UP                                             ▶ Play catch-up · 11m   │
│  ─────────                                                                    │
│  ┌───────────────────────┐   ┌───────────────────────┐   ┌────────────────┐  │
│  │ [cover]  AI · Policy  │   │ [cover]  TECH · CyberS│   │ [cover]  INDIA │  │
│  │ India CERT-In warns…  │   │ New privacy law…      │   │ RBI raises rate│  │
│  │ → Enterprises running │   │ → EU Council backs…   │   │ → Rate hike…   │  │
│  │   Windows 10/11 must  │   │                       │   │   sticky infl. │  │
│  │   patch three CVEs    │   │ 1:12 · 3 sources      │   │ 1:42 · 5 sources│ │
│  │ 1:36 · moneyctrl+2    │   │ Read brief · Orig ↗   │   │ · 3 developments│ │
│  │ Read brief · Orig ↗   │   │                       │   │ Read brief …    │ │
│  └───────────────────────┘   └───────────────────────┘   └────────────────┘  │
│  … (up to 8)                                                                  │
├──────────────────────────────────────────────────────────────────────────────┤
│  WORTH KNOWING                                        + Add to queue · 8      │
│  ─────────────                                                                │
│  … 6-card grid, lower priority than CATCH UP                                  │
├──────────────────────────────────────────────────────────────────────────────┤
│  YOUR BEATS                                                    [List][Globe]  │
│  ──────────                                                                   │
│   ALL · AI · TECH · SCIENCE · SPORTS · US · INDIA · WORLD · BUSINESS          │
│    · Models & Research · Products & Tools · Infrastructure · Policy…          │
│  ┌────┐┌────┐┌────┐┌────┐                                                     │
│  │ .. ││ .. ││ .. ││ .. │  (filtered grid, chronological)                     │
│  └────┘└────┘└────┘└────┘                                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│  EXPLORE / ALL                                        See all 106 →           │
├──────────────────────────────────────────────────────────────────────────────┤
│  ARCHIVE                                                                      │
│  ────────                                                                     │
│    ▸ Fri 12 Sep · 24 stories · 21 min                                         │
│    ▸ Thu 11 Sep · 19 stories · 17 min                                         │
│    ▸ Wed 10 Sep · 22 stories · 20 min                                         │
├──────────────────────────────────────────────────────────────────────────────┤
│  You're caught up. Next fire at 19:00 UTC.                                    │
└──────────────────────────────────────────────────────────────────────────────┘

                                       ┌──────────────────────────────────┐
                                       │ ▶ ...  Now: RBI raises repo rate │
                                       │ moneycontrol · INDIA › Economy   │
                                       │ ═══════════════─────────────     │
                                       │ 0:42 / 1:42   1.0×  Q  ✕         │
                                       └──────────────────────────────────┘
```

### 21.2 Tablet 768 px

```
┌────────────────────────────────────────────────────────┐
│  Briefing.                                              │
│  Vol. 01 · Sun 14 Sep              News · Blogs         │
├────────────────────────────────────────────────────────┤
│  8 meaningful developments · 11 min · ▶ Play catch-up  │
├────────────────────────────────────────────────────────┤
│  CATCH UP                          ▶ Play catch-up      │
│  ─────────                                              │
│  ┌────────────────┐┌────────────────┐                   │
│  │  card 1        ││  card 2        │                   │
│  └────────────────┘└────────────────┘                   │
│  ┌────────────────┐┌────────────────┐                   │
│  │  card 3        ││  card 4        │                   │
│  └────────────────┘└────────────────┘                   │
├────────────────────────────────────────────────────────┤
│  WORTH KNOWING             + Add · 8                    │
│  … 2-col grid                                           │
├────────────────────────────────────────────────────────┤
│  YOUR BEATS                                             │
│  ALL AI TECH SCI SPORTS US INDIA WORLD BUS   [ⓘ Globe]  │
│  … stories                                              │
├────────────────────────────────────────────────────────┤
│  … Explore / Archive collapsed                         │
└────────────────────────────────────────────────────────┘

     [ ▶  RBI raises repo rate     0:42 / 1:42  1.0× Q ✕ ]
```

### 21.3 Mobile 390 px

```
┌────────────────────────────────┐
│ Briefing.                       │
│ Vol. 01 · Sun 14 Sep            │
│ ─────────────────────────────── │
│  [ News ][ Blogs ]              │
├────────────────────────────────┤
│ 8 meaningful developments       │
│ · 11 min · ▶ Play catch-up      │
├────────────────────────────────┤
│ CATCH UP           ▶ Play · 11m │
│ ─────────                        │
│ ┌────────────────────────────┐  │
│ │ [cover]  AI · Policy       │  │
│ │ India CERT-In warns on…    │  │
│ │ → Enterprises running…     │  │
│ │ 1:36 · 3 sources           │  │
│ │ Read brief   Original ↗    │  │
│ └────────────────────────────┘  │
│ ┌────────────────────────────┐  │
│ │ card 2 …                   │  │
│ └────────────────────────────┘  │
│ …                               │
├────────────────────────────────┤
│ WORTH KNOWING       + Add · 8   │
│ …                               │
├────────────────────────────────┤
│ YOUR BEATS                      │
│ ALL AI TECH SCI SPORTS INDIA →  │
│ …                               │
└────────────────────────────────┘

┌────────────────────────────────┐  ← Persistent player, 76 px tall
│ ▶  RBI raises repo rate  1:42  │      Tap → expands to bottom-sheet
│    ═══─────  0:42 / 1:42       │
└────────────────────────────────┘
```

**Bottom-sheet on mobile (expanded):**

```
╭────────────────────────────────╮
│           ═ (grip)              │
│                                 │
│      RBI raises repo rate       │
│      moneycontrol · INDIA       │
│                                 │
│   ═════════─────────            │
│   0:42               1:42       │
│                                 │
│   ⏮   ▶   ⏭                     │
│                                 │
│   1.0×    Queue    Original ↗   │
│                                 │
│   ✕ Close                       │
╰────────────────────────────────╯
```

## 22. Priority classification (P0 / P1 / P2)

### P0 — required to correct the product model

- Hero replaced with change-based framing + session-strip.
- CATCH UP block with "Play catch-up" action.
- "What changed" line on every card (SCAN level).
- `Read brief` / `Original ↗` copy fix.
- `refined by hand` copy fix.
- Completed-state persistence + visual dim.
- "You're caught up" affordance.
- Fix "N°01 / Today" to show only for today's actual lede.
- Player: previous / next + queue.
- Mobile bottom-bar player + bottom-sheet.

### P1 — strong improvement

- WORTH KNOWING as a distinct block.
- Archive collapsed by day.
- Globe demoted to Explore toggle.
- Sports "For you" sub-tab.
- INDIA lens chip.
- Level 3 CONTEXT / TIMELINE / ALL SOURCES rendering.
- Playback speed control.
- Blog card always-visible hook.
- Blog "Recommended this week" strip.
- Queue drawer (keyboard `Q`, mobile bottom-sheet).
- Accessibility polish (aria-labels, focus ring audit, reduced-motion
  extension).

### P2 — optional polish

- Play `<category>` presets pinned in queue drawer.
- Cluster marker `· 3 developments` on cards.
- Cover images lazy-served at exact display width.
- Preload single serif WOFF2.

## 23. Browser acceptance criteria

Live-browser verification required before implementation is signed off.
Same list is the manual + Playwright validation script.

### 23.1 Breakpoints

Test at exactly: **1440 · 1280 · 768 · 390** (and spot-check at 320).

### 23.2 Content states

- 0 new stories (empty CATCH UP → "You're caught up" plate).
- 1 new story.
- 5 new stories.
- 15 new stories (WORTH KNOWING has real content).
- Very long headline (three-line clamp; no overflow).
- Very long source name (chip truncates with ellipsis).
- Complex event timeline (5-entry timeline at Level 3).
- Story with one source (source line reads "1 source").
- Story with five sources (chip expands to list on tap).
- Story with YouTube explainer (Level 2 has "Watch explainer ↗").
- Story with no audio (`audio_path == ""` → card omits duration, no
  play affordance).
- Audio playback queue (queue drawer shows 3 upcoming).
- Completed briefing state (all in CATCH UP marked completed → whole
  block dims, "You're caught up" appears).
- Historical archive (three days collapsed; expand one).

### 23.3 Functional checks

- Hero never shows total-story-count as primary framing.
- "N°01 / Today" appears ONCE, on today's first card only.
- Historical days do NOT show "N°01 / Today".
- `Read brief` expands in place with chevron rotation.
- `Original ↗` opens new tab with `rel="noreferrer"`.
- Completed card: opacity 0.7, cover greyscaled. Replay restores.
- "You're caught up" plate renders when new_since is empty.
- `Play new since last check` button disabled → enabled state changes
  as `lastVisitAt` shifts.
- Queue drawer opens; drag-reorder works; next/prev cycles through it.
- Speed control at 1.25× actually plays at 1.25× (`audio.playbackRate`
  is 1.25 after tap).
- `Recommended this week` shelf on `/blogs` has exactly 3 entries.
- Every blog card shows a `summary_short` hook without expansion.
- `refined by hand` copy is gone site-wide.
- Category tuner works (no regression on filter or sub-strip).
- Globe view opens from Explore toggle (no regression).
- Mobile: no horizontal overflow at 320 / 390 px.
- Mobile: player bottom-bar is tappable, expands to bottom-sheet.
- Mobile: bottom-sheet dismisses on swipe-down or tap-outside.

### 23.4 Accessibility checks

- Full keyboard walk: reach every action with Tab; use Enter / Space /
  Left / Right as documented.
- VoiceOver / NVDA reads landmark structure correctly.
- Contrast: title on card ≥ 7:1, `.card.aged` still ≥ 4.5:1.
- `prefers-reduced-motion` disables all layout-shared transitions and
  the NowPlayingWave animation.
- Focus rings visible on every interactive element.

### 23.5 Performance checks

- Lighthouse (mobile, 4× CPU throttling, 4G):
  - Performance ≥ 90.
  - LCP < 2.5 s.
  - CLS < 0.1.
  - INP < 200 ms.
- Chrome DevTools network:
  - Initial `/` transferred JS < 220 KB gz (Globe not loaded).
  - `feed.json` not blocking LCP.
  - No 4xx/5xx.
- Chrome DevTools Console: zero errors on load, zero warnings other
  than known third-party ones.

### 23.6 Screenshots

Take at each breakpoint × each notable state (CATCH UP populated,
empty, mid-play, queue open, mobile bottom-sheet, Level 3 open,
archive expanded). Attach to implementation PR.

---

## Final validation principle

Applying the brief's final gate to this design:

> Does this interface make Rahul feel:
> "There is a mountain of news I haven't consumed"
> or:
> "I understand what changed and I am caught up"?

The design produces the second feeling by construction:

- The hero measures **change**, not volume.
- The primary block (CATCH UP) is bounded to 3–8 items.
- The primary action (`Play catch-up`) has a finite duration attached.
- The primary success state ("You're caught up") is a first-class
  outcome, not a fallback.
- The full corpus remains accessible under EXPLORE / ARCHIVE but is
  never the default.
- Every card carries the persona's promised value — a "what changed"
  line — before any tap.

North-star preserved: **maximum understanding per minute**, not
maximum consumption.

---

**End of UX / IA / listening design review.** Awaiting approval before
touching code.
