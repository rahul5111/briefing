from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
# Data lives inside the site's public dir so Vercel picks it up directly at
# build time. Reviews live outside the site to keep the deploy small.
DATA_DIR = ROOT / "site" / "public" / "data"
REVIEWS_DIR = ROOT / "data" / "reviews"
AUDIO_DIR = DATA_DIR / "audio"
MANIFEST_PATH = DATA_DIR / "feed.json"
RSS_PATH = DATA_DIR / "rss.xml"
MODEL_DIR = ROOT / ".models"

# Legacy HN-only knobs (kept for reference; live config is in sources.yaml)
HN_MIN_SCORE = 200
HN_LOOKBACK_HOURS = 168
HN_MAX_STORIES = 40

DEDUP_THRESHOLD = 0.82           # slightly tighter now that many sources overlap
RETENTION_DAYS = 7               # rolling 7-day window
MAX_MANIFEST_STORIES = 400       # cap on stored stories (newest wins)
# Hard cap only as a runaway-safety net (a source misconfiguration returning
# thousands). Normally the significance filter is what limits volume.
MAX_NEW_PER_RUN = 60

WORDS_MIN = 150
WORDS_MAX = 360
TTS_WPM = 150

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SITE_TITLE = "Briefing"
SITE_DESCRIPTION = "A personal audio briefing of tech and world news."
SITE_URL = os.environ.get("SITE_URL", "https://briefing.example.com")
CDN_BASE = os.environ.get("CDN_BASE", "")  # jsDelivr base, filled at deploy time
