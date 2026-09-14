# Priya — persona spec + audit prompt family

This document seeds every audit prompt in this session. When we ask "would
the user notice this?" we mean Priya.

---

## 1. Persona: Priya Menon

**Age / role.** 33. Senior PM at a Bengaluru-based B2B SaaS company, previously
at an AI startup. Works from home two days a week; commutes by cab on the
other three. Lives in Indiranagar with a partner who works in banking.

**Why she reads the news.** Three overlapping motivations:

1. **Professional edge.** Needs to sound informed in Monday-morning
   strategy calls. Cares about AI research (not AI hype), enterprise
   SaaS moves, foundational infra (Postgres releases, Rust adoption).
2. **Civic literacy.** Follows Indian domestic politics + policy
   (RBI moves, GST, SEBI actions, Supreme Court rulings), and
   US politics because it moves markets and tech regulation.
3. **Personal joy.** Cricket during IPL / T20 World Cups (moderate
   die-hard: watches finals, checks Cricinfo every morning during
   tournaments). Badminton casually (World Championships, All England,
   Asia Championships). F1 during the season. Marathons because she
   ran the Bengaluru half in 2025.

She wants **positive stories** mixed into the feed — she has active
doom-fatigue and follows @futurecrunch and Reasons To Be Cheerful in
her personal RSS reader. She'll skip a full week of Al Jazeera
conflict reporting if it feels like an unbroken wall of tragedy.

**How she consumes.**

- Morning: 15–25 min while making coffee. Wants **audio** playing in
  the kitchen while she moves around. She does not sit and stare at
  the screen.
- Commute: 30–40 min in the cab, headphones. Ideal for the podcast
  feed. Wants to be able to skip a story with one tap.
- Evening: occasionally scrolls the visual feed on desktop while
  eating dinner, dipping into 2–3 full transcripts.

**What breaks her trust — in order of severity.**

1. **A fact wrong in her domain of expertise.** If a summary
   misstates a fact about product management, an AI paper, IPL
   scores, or Indian policy, she assumes the whole feed is unreliable
   and closes the tab. This is unrecoverable within the session.
2. **Audio mispronunciation of names.** "Kohli" pronounced "coal-ee",
   "Sitharaman" as gibberish, "Anthropic" as "an-throw-pick".
   Immediate cringe; if it happens more than once in a briefing,
   she stops the audio.
3. **Summary that reads like a wire-service ledger.** No context,
   no "why it matters," no attribution. She read 400 words and still
   doesn't know if this is a big deal.
4. **UI truncation.** Titles cut mid-word. Meta bleeding into the
   next card. Images cropped through a face. Cards visibly uneven
   in a grid. Any of these read as "unfinished."
5. **Doom monoculture.** Six consecutive stories about Gaza, floods,
   layoffs, and geopolitics without a single lighter beat. She wants
   *briefing*, not *bleak*.
6. **No context on unfamiliar entities.** A story about "the
   NITI Aayog announced" without saying what NITI Aayog is.
   She's Indian and knows, but her mental model is: if the app
   assumes I know, it's writing for insiders — I get insiders'
   news elsewhere.
7. **Same story from multiple sources not merged.** Seeing three
   near-duplicate cards for the same NBA fine (which we shipped Phase
   2 to solve). If dedup fails she notices.

**What earns her trust — in order of value.**

1. Attribution mid-summary — "Reuters reports…", "the BBC
   characterises it as…". Signals editorial rigour.
2. A specific number where a range would have been fine.
   "Twenty-eight million dollars," not "millions."
3. A note of context on Indian-only entities for the international
   angle, and vice versa on US-only entities for her.
4. Audio that pauses correctly at paragraph breaks. Silence is
   information.
5. Cover images that respect the subject's face and don't crop it.
6. A LIVE badge that's actually live during IPL / All England / the
   Olympics. Not a fake status.
7. Distinctive editorial layout that doesn't look like every other
   AI-generated news reader.

**Categories she will explicitly check when she opens the site:**

- **AI**: Models & Research first (papers, benchmarks). Only then
  Industry (funding, launches).
- **Tech**: Software & Open Source (dev tools she uses). Enterprise
  & Cloud (competitors). Consumer Tech only occasionally.
- **India**: Politics, Economy, Law & Courts, Foreign Relations.
  Skips Society mostly.
- **US**: Politics, Economy, Law & Courts.
- **World**: Politics & Elections, Economy & Trade. Actively
  down-weights Conflict-only stories.
- **Sports**: Cricket, Badminton, Track & Field (during Diamond
  League), F1, Marathons & Endurance. Ignores NFL / NBA / MLB
  entirely.
- **Business**: Markets & IPOs, M&A & Deals, Antitrust & Regulation.
- **Science**: Space & Physics, Biology & Medicine. Loves a Quanta
  piece.
- **(missing today) Positive / Uplift**: she'd click this if it
  existed.

---

## 2. Audit prompt family

Each prompt is a self-contained brief for a sub-agent (or an in-thread
task) so we can parallelize. The persona in §1 is the audience for
every audit.

### P1 — Content depth audit
**Ask.** For every one of the eight main categories, sample 3–5
recent stories (uniform across the current manifest). For each: fetch
the original source article via `pipeline.extract`, then compare
against the stored `summary` + `key_points`. Score on a 1–5 scale:

- **Coverage** — are the key facts from the source present?
- **Context** — does the summary explain *why it matters*?
- **Attribution** — does the summary name the source(s) in-line?
- **Priya-fit** — using §1, would she close this story or share it?

Return a per-category table with concrete "worst summary in this
sample" examples (id + title + one-line diagnosis).

### P2 — Audio quality deep audit
**Ask.** Pick one representative story per main category (8 total).
For each: run `pipeline.audio_validate.validate` and also do a manual
silence-structure inspection. Report WER, verdict, silence stats,
and — separately — a manual read-aloud transcript of the first 30
words with any mispronunciation candidates flagged. Recommend which
audios need re-TTS + which need transcript rewrite (some issues are
in the text, not the voice).

### P3 — Visual + UI audit
**Ask.** Use Playwright at 1440/1024/768/390. For each main-cat tab:

1. Screenshot the fold.
2. Screenshot after clicking one of the sub-chips.
3. Hover the featured card, screenshot the choreography.
4. Open one story into the player, screenshot the player state.

Report every visible issue: image crops through faces, title
truncation, meta collision, card unevenness, sub-strip legibility,
player dominance, empty states. Cross-reference §1 for what would
irritate Priya vs. what's cosmetic.

### P4 — Category coverage gap audit
**Ask.** Query the manifest: how many stories in each main + sub
category over the last 24h and last 7d? Which subs are chronically
empty? Which are over-represented (e.g., is SPORTS/Basketball
dominant when it shouldn't be for Priya)? Cross-reference the
"categories she checks" list in §1 and produce a coverage-gap
matrix.

### P5 — Source research + recommendations
**Ask.** Independently research and recommend open RSS/API feeds
for every gap P4 surfaces. Focus areas we know are thin:

- **Positive/uplift**: Good News Network, Reasons To Be Cheerful,
  Future Crunch, Positive.News, Optimist Daily.
- **Cricket**: Cricbuzz feed, Cricinfo statsguru posts, ICC news.
- **Badminton**: BWF news feed, badmintonasia.
- **F1 & motorsport**: Autosport, F1.com, The Race.
- **AI research (not PR)**: arXiv daily cs.LG, Papers with Code
  trending, Anthropic Research blog, Ai2, HuggingFace papers.
- **Indian regional**: The Print, Moneycontrol, Business Standard,
  Indian Business Line.
- **Enterprise**: The Information (paywalled RSS but partial via
  Google News proxy), Protocol archive.
- **Long-form**: Aeon, LongReads, Nautilus.
- **Marathons/Endurance**: Runner's World, LetsRun.com.

For each recommendation, test the RSS URL is live, report items
returned, and slot it into `sources.yaml` with a tier comment.

### P6 — Watermelon.sh UI mining
**Ask.** Fetch https://ui.watermelon.sh/. Identify 3–5 UI components
or interaction patterns that fit within the design lock (light
theme, single vermilion accent, editorial, no glitter, respects
prefers-reduced-motion). For each: name it, describe what it does,
propose a concrete application on this feed (e.g., "for the player's
now-playing indicator", "for the sub-strip active state", "for
category transitions").

### P7 — Consolidated ship list
**Ask.** After P1–P6 return, produce one prioritized punch list
grouped as:

- **P0 — Trust-breaking.** Fixes that stop Priya closing the tab.
  Mispronunciations, factual gaps, image face-crops. Ship first,
  deploy immediately after each.
- **P1 — Visible polish.** Truncation, alignment, layout
  refinement. Batch into one deploy.
- **P2 — Delight.** New UI patterns from P6, positive/uplift bucket
  UI, category-transition animation. Batch after P0/P1 land.

Each item annotated with: what it is, why Priya notices, the file(s)
to touch, an effort estimate. Then execute in order.

---

## 3. Execution rules

- The persona is the *audience*, not the author. When writing
  copy or naming a new UI element, don't put "Priya" in it.
- Every deploy after a P0 or P1 fix must be verified by re-running
  `site/audit.mjs`. Every deploy after a P2 fix must be verified
  in a fresh browser at 1440.
- Do not skip source research (P5) — most content-depth complaints
  are actually coverage gaps.
- If any audit surfaces a fix that's out of scope for this session
  (e.g., requires a new API key), add it to `PLAN.md` under a
  "future work" heading; do not silently drop it.
