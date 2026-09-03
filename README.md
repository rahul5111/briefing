# Briefing

A personal audio briefing of the day's tech, science, and world news. Stories
are pulled from ~20 sources (Hacker News, RSS blogs, Reddit, TLDR newsletters,
Science Daily, world-news wires), filtered for significance, refined through a
multi-pass LLM pipeline, validated end-to-end with Whisper, and rendered as
MP3s via local Kokoro TTS.

Live at **https://briefing-psi-ten.vercel.app**. The pipeline runs three times
a day on free tiers (GitHub Actions cron + Google Gemini free tier + Vercel
hobby). Total monthly cost: $0.

For the durable roadmap and category taxonomy see [`PLAN.md`](./PLAN.md) — it
is authoritative across sessions. This README covers the shipped state.

## Stack

| Layer | Tech |
|---|---|
| Sources | HN (Algolia) · RSS (Verge, Ars, TechCrunch, MIT TR, BBC, Reuters, Al Jazeera, Stratechery, Platformer, Science Daily) · Reddit (programming, worldnews) · TLDR (tech / ai / webdev / infosec / design) |
| Extract | trafilatura (article body + og:image) |
| Dedup | sentence-transformers (MiniLM-L6-v2), threshold 0.82 |
| Significance gate | Gemini scoring (IMPORTANT / INTERESTING / ORDINARY / TRIVIAL / PROMOTIONAL) |
| Refinement | Multi-pass Gemini (`gemini-3.5-flash-lite`) — key-points → draft → hallucination check → coverage gate → audio rewrite → deterministic pronunciation normalize → sanity pass |
| TTS | Kokoro-82M via `kokoro-onnx` (local CPU), `am_liam` at 1.08× with real silence gaps |
| Audio validation | `faster-whisper` (`tiny.en`) round-trip: WER / CER / silence-gap analysis |
| Orchestration | GitHub Actions cron `0 12,19,2 * * *` (3× daily UTC) |
| Site | Astro 5 + React 19 island (Framer Motion), Bricolage Grotesque / Inter Tight / JetBrains Mono, react-globe.gl |
| Hosting | Vercel (deployed from GHA via `VERCEL_TOKEN`) |
| Storage | Repo-committed `site/public/data/` — single source of truth for feed + audio |

## How the pipeline works

1. **Fetch** — `pipeline/sources.yaml` drives per-source adapters
   (`pipeline/sources/*.py`) with a round-robin cap so no single source drowns
   the others.
2. **Extract** — trafilatura pulls the article body + `og:image`.
3. **Dedup** — MiniLM embeddings, cosine ≥ 0.82 → duplicate.
4. **Significance gate** (`significance.py`) — cheap Gemini call scores each
   title; only `IMPORTANT` + `INTERESTING` continue.
5. **Refinement** (`refine.py`) — many cheap LLM passes before spending TTS
   budget:
   1. `key_points.distill` — extract 5–8 must-include facts
   2. `_draft` — first-pass summary
   3. `_local_verify` (regex) → `_redraft` if hallucinated numbers/names
   4. `key_points.coverage` on draft; if <85 % → `_expand_for_coverage`
   5. `_audio_rewrite` — spoken cadence (numbers spelled out, acronyms
      letter-spaced, short sentences)
   6. `_pronunciation` — deterministic regex normalize (`normalize.py`)
   7. Final coverage check on normalized text
   8. `_sanity` — final read-aloud LLM check
   9. Write review to `data/reviews/YYYY-MM-DD/{id}.txt` for spot-check
6. **TTS** (`tts.py`) — chunked Kokoro with real sentence pauses
   (0.32s sentence, 0.60s paragraph). Voice mapped by category:
   AI/STARTUPS/DEV → `am_michael`, WORLD/SECURITY → `am_liam`,
   RESEARCH → `bm_george`, default `am_liam`. Speed `1.08×`.
7. **Audio validation** (`audio_validate.py`) — Whisper transcribes the MP3
   and compares to input. GOOD (WER <10 %) / ACCEPTABLE (<20 %) / POOR.
8. **Manifest + RSS** — writes `feed.json` and `rss.xml`.
9. **Commit + push** — the GHA workflow commits the new data back to the repo
   and Vercel picks it up on the next build.

Data path (single source of truth):
```
site/public/data/
  feed.json
  rss.xml
  audio/YYYY-MM-DD/*.mp3
```

Reviews (per-story refinement transcripts, gitignored):
```
data/reviews/YYYY-MM-DD/*.txt
```

## First-time setup

### 1. Get a Google Gemini API key (free)

- https://aistudio.google.com/app/apikey → create key
- The pipeline defaults to `gemini-3.5-flash-lite`. The `-lite` variant has a
  separate, larger free-tier quota than the top-tier Flash models (which have
  tightened to ~20 requests/day).

### 2. Push the repo

```bash
gh repo create briefing --public --source=. --push
```

### 3. Wire Vercel

Link the repo to a Vercel project once via `vercel link` from `site/`. Then
set these three GitHub Actions secrets so the workflow can deploy without an
interactive Vercel Login Connection:

- `GEMINI_API_KEY`
- `VERCEL_TOKEN` (from https://vercel.com/account/tokens)
- `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` (from `site/.vercel/project.json`)

### 4. Trigger the first run

Repo → Actions → **briefing-pipeline** → Run workflow.

First run downloads Kokoro (~350 MB) and takes ~8 minutes; subsequent runs
finish in 3–5 minutes.

### 5. (Optional) Subscribe as a podcast

The pipeline writes `site/public/data/rss.xml`. Point Overcast / Pocket Casts /
Apple Podcasts at:

```
https://briefing-psi-ten.vercel.app/data/rss.xml
```

## Running the pipeline locally

Python 3.12 (Kokoro ONNX + torch have no wheels for 3.14+):

```bash
cd /Users/rahul5111/Desktop/newsbriefing
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r pipeline/requirements.txt

# .env is gitignored; chmod 600
printf 'GEMINI_API_KEY=your-key\n' > .env && chmod 600 .env

set -a && source .env && set +a && python -m pipeline.run
```

Useful entry points:

- `python -m pipeline.run` — full pipeline
- `python -m pipeline.mock_test` — dry-run against fixtures (no TTS spend)
- `python -m pipeline.test_one <story_id>` — re-synthesize a single story
- `python -m pipeline.revalidate` — re-run Whisper validation on existing MP3s

## Running the site locally

```bash
cd site
npm install
npm run dev
```

The site reads `public/data/feed.json` directly — no symlink or CDN indirection.

## Configuration

**Ingestion:** add / disable sources in `pipeline/sources.yaml`. RSS, HN,
Reddit, and TLDR types need no code change. See PLAN.md § 2 for planned
Google News feeds.

**Pipeline knobs** (`pipeline/config.py`):

- `DEDUP_THRESHOLD = 0.82`
- `MAX_NEW_PER_RUN = 60` (safety cap; significance gate normally limits volume)
- `RETENTION_DAYS = 7`
- `MAX_MANIFEST_STORIES = 400`
- `WORDS_MIN / WORDS_MAX = 150 / 360`
- `GEMINI_MODEL = "gemini-3.5-flash-lite"` (override via env var)

**Voice** (`pipeline/tts.py`): `VOICE_BY_CATEGORY`, `SPEED = 1.08`, gap
durations. Never change without approval — see the voice notes in PLAN.md.

## Category taxonomy

**Locked in PLAN.md § 1** (8 top-level with subcategories):

`AI · Tech · Science · Sports · US · India · World · Business`

The classifier in `pipeline/categorize.py` still uses the older 6-cat scheme
(`AI / STARTUPS / SECURITY / DEV / RESEARCH / WORLD`). Rewriting it to emit
`{main, sub}` is PLAN item **A2**; batch re-classification is **A3**.

## Design

Light theme only. Single vermilion accent `#E14522` everywhere (globe pins,
tabs, links). Warm bone `#F1EEE6` background, charcoal ink text. Bricolage
Grotesque display, Inter Tight body, JetBrains Mono meta. Full-width magazine
grid (max 1600px, 5vw padding), first card of each day featured 2×2. Missing
images render as Bauhaus-inspired `AbstractCover` SVGs — never a raw letter
placeholder.

See PLAN.md for the shipped-vs-pending UI work list.

## Known trade-offs

- **LLM hallucinations** — the coverage + sanity + Whisper round-trip catches
  most, but a small residue survives. Review files in `data/reviews/` make
  spot-checks cheap.
- **Kokoro pronunciations** — `pipeline/normalize.py` handles the common
  cases (numbers, acronyms, common tech terms). Non-English proper nouns can
  still slip; extend the normalizer as needed.
- **Free-tier quota** — Gemini free tier is generous for `-lite` models but a
  large re-classification job (PLAN A3) will need to be chunked.
- **Public URL** — the site currently has no auth gate. Turn on Vercel
  Password Protection or a Cloudflare Access shim before sharing.

## Layout

```
newsbriefing/
├── PLAN.md                 # durable roadmap (read first)
├── README.md               # this file
├── .github/workflows/
│   └── pipeline.yml        # cron 0 12,19,2 * * *
├── pipeline/               # Python 3.12 pipeline
│   ├── sources/            # per-source adapters (hn, rss, reddit, tldr, gmail)
│   ├── sources.yaml        # ingestion config
│   ├── run.py              # orchestrator
│   ├── refine.py           # multi-pass content refinement
│   ├── tts.py              # chunked Kokoro synthesis
│   ├── audio_validate.py   # Whisper round-trip
│   ├── significance.py     # importance gate
│   ├── categorize.py       # category classifier (pending A2 rewrite)
│   └── ...
├── site/                   # Astro 5 + React 19
│   ├── src/components/     # Feed, AbstractCover, Globe, Player, ...
│   ├── src/styles/
│   └── public/data/        # feed.json, rss.xml, audio/  (committed)
└── data/reviews/           # per-story refinement transcripts (gitignored)
```
