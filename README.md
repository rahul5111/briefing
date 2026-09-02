# Briefing

A personal audio briefing of tech and world news. HN top stories are fetched,
extracted, summarized as 150–360-word audio scripts, and rendered as MP3s via
Kokoro TTS. A static Astro site lists them; the same feed is exposed as a
podcast RSS.

Everything runs on free tiers.

## Stack

| Layer | Tech |
|---|---|
| Source | HN Algolia API |
| Extract | trafilatura |
| Dedup | sentence-transformers (MiniLM-L6-v2) |
| Summarize | Google Gemini 2.0 Flash |
| TTS | Kokoro-82M via kokoro-onnx (local, CPU) |
| Orchestration | GitHub Actions (cron every 4h) |
| Storage | Git repo + jsDelivr CDN |
| Site | Astro + React island (motion/react) |
| Hosting | Cloudflare Pages |
| Access | Cloudflare Access (password gate) |

## First-time setup

### 1. Get a Google Gemini API key (free)

- Go to https://aistudio.google.com/app/apikey
- Create an API key
- Copy it — you'll add it to GitHub Secrets in step 3

Free tier: ~1,500 requests/day of `gemini-2.0-flash`. The pipeline uses ~20/run.

### 2. Push this project to a new GitHub repo

```bash
cd /Users/rahul5111/Desktop/newsbriefing
git init
git add .
git commit -m "initial commit"
gh repo create briefing --public --source=. --push
```

The repo needs to be **public** for jsDelivr to serve the audio files. If you
want it private, swap `CDN_BASE` in the workflow to a signed URL scheme.

### 3. Add secrets in GitHub

Repo → Settings → Secrets and variables → Actions:

- **Secret** `GEMINI_API_KEY` = your key from step 1
- **Variable** `SITE_URL` = the URL you'll get from Cloudflare Pages in step 4
  (you can set this after step 4 finishes)

### 4. Deploy the site on Cloudflare Pages

- Cloudflare dashboard → Workers & Pages → Create → Pages → Connect to Git
- Pick the `briefing` repo
- Build settings:
  - Framework preset: **Astro**
  - Build command: `cd site && npm install && npm run build`
  - Build output: `site/dist`
  - Root directory: (leave blank)
  - Environment variables:
    - `PUBLIC_CDN_BASE` = `https://cdn.jsdelivr.net/gh/<your-user>/briefing@main/data`
- Deploy

You'll get a URL like `briefing-abc.pages.dev`. Set this as the `SITE_URL`
variable in step 3.

### 5. Password-gate the site with Cloudflare Access (free)

- Zero Trust dashboard → Access → Applications → Add an application → Self-hosted
- Application domain: `briefing-abc.pages.dev`
- Session duration: 1 month
- Policy: name it "me", action = Allow, include = Emails → your email
- Save. Now the site requires a one-time email code to view.

### 6. Trigger the first run

Repo → Actions → briefing-pipeline → Run workflow

First run downloads the Kokoro model (~350 MB) and takes ~10 minutes. Subsequent
runs use the cached model and finish in 3–5 minutes.

After it completes, the site rebuilds automatically and your first batch of
stories appears.

### 7. (Optional) Subscribe as a podcast

The workflow writes `data/rss.xml`. Add this URL in Overcast / Pocket Casts:

```
https://cdn.jsdelivr.net/gh/<your-user>/briefing@main/data/rss.xml
```

Now you also get episodes pushed to your phone automatically.

## Running the pipeline locally

Use Python 3.12 (Kokoro's ONNX runtime and torch have no wheels for 3.14+):

```bash
cd /Users/rahul5111/Desktop/newsbriefing
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r pipeline/requirements.txt

# put your key in .env once (chmod 600, gitignored)
printf 'GEMINI_API_KEY=your-key\n' > .env && chmod 600 .env

set -a && source .env && set +a && python -m pipeline.run
```

First run downloads the Kokoro model to `.models/` (~350 MB) and takes 5–10
minutes. Subsequent runs finish in 3–5 minutes.

Audio files land in `data/audio/YYYY-MM-DD/`, manifest in `data/feed.json`,
podcast feed in `data/rss.xml`.

### Which Gemini model

`pipeline/config.py` defaults to `gemini-3.5-flash-lite` because Google's free
tier for the top-tier Flash models has tightened to ~20 requests/day per model.
The `-lite` variant is a separate quota bucket and comfortably handles a
20-story batch. Override with `GEMINI_MODEL=your-model` if a future model has a
better free-tier fit.

## Running the site locally

```bash
cd site
pnpm install
pnpm dev

# in another terminal, symlink so the dev server can serve audio files
# that live outside site/public
ln -sfn ../../data site/public/data
```

The symlink is needed for local dev because Astro only serves files under
`site/public/`. In production, audio is served from jsDelivr via
`PUBLIC_CDN_BASE`, so no symlink needed there.

## Tuning

All knobs are in `pipeline/config.py`:

- `HN_MIN_SCORE` — story score threshold (default 150)
- `HN_LOOKBACK_HOURS` — how far back to look (default 24)
- `HN_MAX_STORIES` — max stories per run (default 20)
- `WORDS_MIN` / `WORDS_MAX` — summary length bounds (150–360)
- `DEDUP_THRESHOLD` — cosine similarity above which stories are considered
  duplicates (default 0.86)
- `RETENTION_DAYS` — how long to keep old audio (default 14)

Voice-per-category mapping is in `pipeline/tts.py` (`VOICE_BY_CATEGORY`).

## Adding more sources later

The pipeline is written around `fetch.Candidate`. To add RSS feeds (BBC,
Reuters, Ars, etc.), write a `fetch_rss.py` that yields `Candidate` objects and
merge its output with `fetch_top_stories()` in `run.py`. Everything downstream
is source-agnostic.

## Known trade-offs

- **Summarization accuracy** — Gemini Flash occasionally invents a detail. The
  post-hoc verifier in `summarize.py` drops sentences with numbers or proper
  nouns not present in the source and asks for one retry. Not perfect.
- **Kokoro pronunciations** — non-English names get mangled. To fix, maintain a
  `pronunciations.json` mapping and pre-process text in `tts.py`.
- **jsDelivr caching** — audio files may take a few minutes to appear on the
  CDN after commit. jsDelivr cache TTL is 12h; use `?v=<sha>` to bust if needed.
- **Repo bloat** — retention keeps this to ~2 GB max. If it grows past that,
  drop `RETENTION_DAYS` or move audio to Cloudflare R2 (10 GB free).
- **Copyright** — the Cloudflare Access gate keeps this personal. Do not turn
  off the gate and publish the URL.
