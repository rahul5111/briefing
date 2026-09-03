# Briefing — active plan

Last updated: 2026-09-03

This document is the persistent working plan across sessions. Update it as
items complete or change; do not rely on session memory alone.

---

## 1. Category taxonomy (locked)

Eight top-level categories. Each has 4–8 subcategories. Every story is tagged
with `{main, sub}` and, where relevant, `location`.

### Top-level: `AI · Tech · Science · Sports · US · India · World · Business`

### AI — models, apps, research, policy
| Sub | Definition |
|---|---|
| Models & Research | New LLM releases, ML papers, benchmarks, novel training techniques |
| Products & Tools | Consumer/dev AI products built on models (Cursor, Sora, Claude Code, image gens, agents) |
| Infrastructure | AI-specific chips, GPUs, TPUs, inference clouds, training compute |
| Policy & Safety | Regulation, alignment research, executive orders, ethics/safety court cases |
| Industry | Non-earnings AI-company strategy, funding, leadership |

### Tech — software, hardware, startups, security
| Sub | Definition |
|---|---|
| Software & Open Source | Languages, frameworks, libraries, dev tools, OSS releases |
| Startups | YC batches, indie launches, pre-Series-C product debuts, Show HN standouts |
| Consumer Tech | Phones, laptops, wearables, cameras, smart-home devices |
| Enterprise & Cloud | B2B SaaS, cloud services, infra companies |
| Security & Privacy | Breaches, CVEs, exploits, privacy scandals, incident response |
| Gaming | Game launches, consoles, VR/AR, headline esports |

### Science — discovery, research, breakthroughs
| Sub | Definition |
|---|---|
| Space & Physics | Astronomy, cosmology, JWST/Hubble, particle physics, fusion, quantum |
| Biology & Medicine | Genetics, drugs, CRISPR, clinical trials, longevity, disease outbreaks (research angle) |
| Climate & Environment | Climate research, energy-transition science, biodiversity, ocean/atmospheric |
| Materials & Chemistry | New materials, superconductors, battery chemistry, industrial chemistry |
| Engineering & Robotics | Non-AI robotics, feats of engineering, spacecraft, medical devices |
| Awards & Patents | Nobel, Turing, Fields, notable patents |

### Sports — user-priority-ordered
| Priority | Sub | Definition |
|---|---|---|
| 🔴 live | Major Events | Olympics · Asian Games · Commonwealth Games · World Cups · live tournament updates |
| ⬆︎ | Badminton | BWF World Tour, All England, Asia Championships |
| ⬆︎ | Track & Field | Diamond League, World Athletics, records |
| ⬆︎ | Cricket | IPL, T20 World Cup, ODI series, Test matches |
| ⬆︎ | Tennis | Grand Slams, major finals |
| ⬆︎ | Cycling | Tour de France, Giro, Vuelta, world championships |
| ⬆︎ | Boxing & MMA | Title fights, UFC main events, heavyweight bouts |
| ⬆︎ | Marathons & Endurance | Boston · London · Berlin · Chicago · Tokyo · NY · Ironman |
| — | Motorsport | F1, MotoGP, IndyCar |
| — | Soccer | Premier League, Champions League, La Liga, MLS, World Cup |
| — | Basketball | NBA, EuroLeague, WNBA |
| — | Golf | Majors only (Masters, US Open, PGA, Open) |
| ⬇︎ | Other | American football, baseball, hockey, rugby, everything else |

Live-updates behavior: when a Major Events tournament is running, that
subcategory floats to the top of Sports and gets a small pulsing "LIVE" dot
(the only real semantic use of a dot on the site).

### US — new top-level
| Sub | Definition |
|---|---|
| Politics | Federal politics, elections, executive orders, congressional actions |
| Economy | Jobs report, Fed decisions, inflation, GDP, consumer spending |
| Law & Courts | SCOTUS rulings, DOJ actions, federal court cases |
| Health | CDC, FDA, health policy, US disease outbreaks |
| Disasters | Hurricanes, wildfires, floods, mass-casualty events in US |
| Policy Changes | Federal legislation, EPA/FCC/EEOC rules |
| Society | Protests, civil rights, education, immigration |

### India — new top-level
| Sub | Definition |
|---|---|
| Politics | Parliament, elections, PM and state CMs, party moves |
| Economy | RBI, Union Budget, GST, GDP, corporate India regulation |
| Law & Courts | Supreme Court, high courts, major rulings, PILs |
| Health | Health policy, disease outbreaks, hospital-system news |
| Disasters | Cyclones, floods, earthquakes, industrial accidents |
| Policy Changes | New central/state laws, regulations |
| Society | Protests, communal events, education, caste/religion |
| Foreign Relations | India-US, India-China, Quad, BRICS, neighborhood diplomacy |

### World — non-US, non-India
| Sub | Definition |
|---|---|
| Politics & Elections | Non-US non-India political events |
| Conflict & Security | Wars, ceasefires, terrorism, military moves |
| Economy & Trade | Non-US/India economies, cross-border trade, sanctions |
| Climate & Disasters | Outside US and India |
| Society & Culture | Global cultural moments, human rights |
| Health & Public Policy | WHO, pandemics, cross-border health |

### Business — corporate, markets, deals
| Sub | Definition |
|---|---|
| M&A & Deals | Acquisitions, mergers, PE buyouts, spin-offs |
| Markets & IPOs | IPOs, direct listings, earnings surprises, stock movements |
| Leadership & Layoffs | C-suite changes, ousters, layoffs, org restructures |
| Finance & Fintech | Banks, crypto, payments, financial-product news |
| Antitrust & Regulation | SEC, DOJ, EU actions against specific companies |
| Retail & Consumer | Amazon/Walmart moves, DTC brands, retail earnings |

### Cross-category priority (when a story straddles)
`Science → AI → Sports → Tech → Business → US → India → World`

If US or India tags apply strongly, prefer them over generic World.

---

## 2. New source: Google News

Google News exposes RSS at:
- Top: `https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en`
- Topic: `https://news.google.com/rss/topics/<topic-id>?hl=en-US&gl=US&ceid=US:en`
- Search: `https://news.google.com/rss/search?q=<query>&hl=en-US`
- India edition: `https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en`

Uses the existing `rss` source adapter. To add: entries in `pipeline/sources.yaml`
for top / US / India / Business / Sports / Tech.

---

## 3. Cross-source enrichment (major pipeline change)

Current behavior:
```
new candidates → semantic dedup → drop duplicates → refine → TTS
```

Proposed:
```
new candidates → semantic dedup
  ├─ if UNIQUE:      normal pipeline (refine → TTS)
  └─ if DUPLICATE:   MERGE PATH ↓
                     ├─ extract new source's article text
                     ├─ LLM compare: what does new source add?
                     │  (facts, quotes, context, opposing view)
                     ├─ if new material adds ≥15% new information:
                     │  ├─ neutral synthesis: rewrite as bias-balanced
                     │  │  merged version using facts from both
                     │  ├─ append new source to story's `sources[]`
                     │  ├─ RE-TTS the merged version
                     │  └─ replace audio + summary in place
                     └─ else: append source to `sources[]` (no re-TTS)
```

Story schema additions:
```json
{
  "id": "...",
  "sources": [
    { "name": "verge", "url": "...", "domain": "theverge.com", "added_at": "..." },
    { "name": "bbc_world", "url": "...", "domain": "bbc.com", "added_at": "..." }
  ]
}
```

UI: card shows "3 sources" when `sources.length > 1`. Player meta shows the
primary source and a small "+2 more" chip that expands.

Cost:
- ~2 extra Gemini calls per detected duplicate (delta detection + synthesis)
- Re-TTS ~30–60s per merged story on GHA runner
- Gated on real new information (delta threshold), so many duplicates are
  cheap `sources[]` appends with no LLM/TTS cost.

---

## 4. Sequenced action list

### Phase 1 — foundation and taxonomy (safe, incremental)

- [ ] **A1** Approve taxonomy above (this file locked)
- [ ] **A2** Rewrite classifier: outputs `{main, sub}` per story
- [ ] **A3** Batch re-classify existing stories with new taxonomy
- [ ] **A4** Add `sources: [...]` array to story schema; backfill single-source entries
- [ ] **B1** Add Google News RSS sources (top / US / India / Tech / Business / Sports)
- [ ] **D1** Two-level nav: 8 top-level tabs + expanding subcategory strip under active tab
- [ ] **D4** UI overlap fix: Playwright screenshots at 1440/1024/768/390, iterate until zero overlap

### Phase 2 — cross-source enrichment (bigger, needs careful rollout)

- [ ] **C1** Change dedup: when duplicate detected, LOG it (do not drop yet — observation only)
- [ ] **C2** Add delta-detection LLM step (does new source add real info?)
- [ ] **C3** Add neutral-synthesis LLM step (produce merged bias-balanced version)
- [ ] **C4** Wire re-TTS on updated summary; update `sources[]`

### Phase 3 — polish + operations

- [ ] **D2** Card UI shows `N sources` when > 1
- [ ] **D3** Live tournament badge in Sports > Major Events
- [ ] **E1** Trigger pipeline run with new sources + taxonomy
- [ ] **E2** Full-page screenshot audit at every breakpoint

---

## 5. Recent decisions log

| Date | Decision |
|---|---|
| 2026-09-03 | Renamed `Development` → `Tech` (broader scope, includes hardware + consumer + security + gaming) |
| 2026-09-03 | Added subcategories to every top-level category |
| 2026-09-03 | Added `US` and `India` as their own top-level categories (was in `World`) |
| 2026-09-03 | Sports re-ordered by user priority: badminton / track / cricket / boxing / marathons / cycling elevated; American football demoted to `Other` |
| 2026-09-03 | Cross-source enrichment approved as Phase 2 major work |
| 2026-09-03 | Google News confirmed scrapable via RSS; added as source |

---

## 6. Working state (for next session pick-up)

**Live URL:** https://briefing-psi-ten.vercel.app
**Repo:** https://github.com/rahul5111/briefing
**Pipeline cron:** 3× daily at 12/19/02 UTC via GHA (`.github/workflows/pipeline.yml`)
**Data path:** `site/public/data/{feed.json,rss.xml,audio/YYYY-MM-DD/*.mp3}`
**Review path (multi-pass refinement outputs):** `data/reviews/YYYY-MM-DD/*.txt`

**Auth wired:**
- `GEMINI_API_KEY` (in `.env` locally, GH secret in CI)
- `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` (GH secrets)
- Gmail integration scaffolded but disabled (`enabled: false` in sources.yaml) — awaits user OAuth flow

**Not yet done from earlier feedback:**
- UI overlap bugs still present (needs Playwright audit at all breakpoints)
- Category naming still uses old 6-cat taxonomy (`AI/STARTUPS/SECURITY/DEV/RESEARCH/WORLD`) — Phase 1 rewrites this
- Gmail newsletter ingestion pending user's OAuth (or user may skip if TLDR covers most)
