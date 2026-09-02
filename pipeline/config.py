from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
AUDIO_DIR = DATA_DIR / "audio"
MANIFEST_PATH = DATA_DIR / "feed.json"
RSS_PATH = DATA_DIR / "rss.xml"
MODEL_DIR = ROOT / ".models"

HN_MIN_SCORE = 150
HN_LOOKBACK_HOURS = 24
HN_MAX_STORIES = 20

DEDUP_THRESHOLD = 0.86
RETENTION_DAYS = 14

WORDS_MIN = 150
WORDS_MAX = 360
TTS_WPM = 150

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SITE_TITLE = "Briefing"
SITE_DESCRIPTION = "A personal audio briefing of tech and world news."
SITE_URL = os.environ.get("SITE_URL", "https://briefing.example.com")
CDN_BASE = os.environ.get("CDN_BASE", "")  # jsDelivr base, filled at deploy time
