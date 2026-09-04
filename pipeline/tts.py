"""Chunked Kokoro TTS with real silence pauses.

Kokoro's single-call output has two problems:
  - It silently clips past ~500 tokens on some voices
  - It flattens the natural rhythm between sentences

Fix: split the refined text by sentence, synthesize each chunk separately, and
concatenate with real silence between them. Sentence gaps get a short pause,
paragraph gaps (double-newline in the input) get a longer one.
"""
from __future__ import annotations
import re
import urllib.request
from pathlib import Path
import numpy as np
import soundfile as sf
from . import config


_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"


# News-anchor voice palette. am_liam is mature, warm, and reads with the
# cadence of an evening bulletin — the opposite of the previous soft-whisper
# default. Kept a fallback map for future per-category voicing.
VOICE_BY_CATEGORY = {
    "WORLD":    "am_liam",       # anchor voice for hard news
    "SECURITY": "am_liam",
    "AI":       "am_michael",    # crisper, energetic
    "STARTUPS": "am_michael",
    "DEV":      "am_michael",
    "RESEARCH": "bm_george",     # British, informative feel
    "default":  "am_liam",
}

SPEED = 1.08              # +8% brings it out of "whispering" territory
GAP_SENTENCE_S = 0.32     # slightly longer for more dramatic pace
GAP_PARAGRAPH_S = 0.60
GAP_OPEN_S = 0.15
GAP_TAIL_S = 0.35

_kokoro = None


def _ensure_models() -> tuple[Path, Path]:
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model = config.MODEL_DIR / "kokoro-v1.0.onnx"
    voices = config.MODEL_DIR / "voices-v1.0.bin"
    if not model.exists():
        print(f"Downloading Kokoro model to {model}...")
        urllib.request.urlretrieve(_MODEL_URL, model)
    if not voices.exists():
        print(f"Downloading Kokoro voices to {voices}...")
        urllib.request.urlretrieve(_VOICES_URL, voices)
    return model, voices


def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        model, voices = _ensure_models()
        _kokoro = Kokoro(str(model), str(voices))
    return _kokoro


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# A fragment ending in " X." (single capital letter + period, preceded by
# whitespace or start-of-string) is almost certainly a letter-spaced
# acronym mid-sentence, not a real sentence end. We use this to re-merge
# fragments that a naive sentence split would incorrectly break up.
#
# Matches:  "N."   " B."   "The N. B. A."   "The K. L. two"
# Rejects:  "LLC." "USA." "3.14." — the letter isn't isolated
_ACRONYM_TAIL = re.compile(r"(?:^|\s)[A-Z]\.$")


def _split_into_units(text: str) -> list[tuple[str, str]]:
    """Return [(kind, chunk)] where kind is 'sentence' or 'paragraph_break'.

    Paragraphs are split on double-newline. Within a paragraph, we split on
    sentence-ending punctuation but keep the punctuation attached to the
    preceding chunk so the TTS keeps the intonation. Fragments that were
    split inside a letter-spaced acronym (e.g. "N. B. A. and the league"
    → "N.", "B.", "A.", "and the league") get re-merged so the acronym is
    read as one continuous sequence.
    """
    units: list[tuple[str, str]] = []
    paragraphs = re.split(r"\n\s*\n", text.strip())
    for pi, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue
        raw = _SENTENCE_SPLIT.split(para)
        merged: list[str] = []
        for frag in raw:
            frag = frag.strip()
            if not frag:
                continue
            if merged and _ACRONYM_TAIL.search(merged[-1]):
                merged[-1] = merged[-1] + " " + frag
            else:
                merged.append(frag)
        for s in merged:
            if len(s) > 280:
                for p in _soft_split_long(s):
                    units.append(("sentence", p))
            else:
                units.append(("sentence", s))
        if pi < len(paragraphs) - 1:
            units.append(("paragraph_break", ""))
    return units


def _soft_split_long(sentence: str, target: int = 220) -> list[str]:
    """Break an overlong sentence at commas or conjunctions."""
    if len(sentence) <= target:
        return [sentence]
    parts: list[str] = []
    remaining = sentence
    while len(remaining) > target:
        cut = -1
        for sep in (", ", "; ", " and ", " but ", " while "):
            idx = remaining.rfind(sep, 0, target)
            if idx > target * 0.5:
                cut = idx + len(sep)
                break
        if cut < 0:
            cut = target
        piece = remaining[:cut].rstrip(" ,;")
        if not piece.endswith((".", "!", "?")):
            piece += "."
        parts.append(piece)
        remaining = remaining[cut:].lstrip()
    if remaining:
        if not remaining.endswith((".", "!", "?")):
            remaining += "."
        parts.append(remaining)
    return parts


def _silence(seconds: float, sample_rate: int) -> np.ndarray:
    return np.zeros(int(seconds * sample_rate), dtype=np.float32)


def synth(text: str, out_path: Path, category: str = "default") -> dict:
    """Synthesize `text` into an mp3 at `out_path`. Returns a stats dict."""
    if not text or not text.strip():
        raise ValueError("empty text")

    k = _get_kokoro()
    voice = VOICE_BY_CATEGORY.get((category or "").upper(), VOICE_BY_CATEGORY["default"])

    units = _split_into_units(text)
    if not units:
        raise ValueError("no synthesizable units after split")

    segments: list[np.ndarray] = []
    sr: int | None = None

    # Pre-roll
    segments.append(_silence(GAP_OPEN_S, 24000))  # placeholder sr, replaced

    chunks_synthed = 0
    for i, (kind, chunk) in enumerate(units):
        if kind == "paragraph_break":
            if sr:
                segments.append(_silence(GAP_PARAGRAPH_S, sr))
            continue

        samples, s = k.create(chunk, voice=voice, speed=SPEED, lang="en-us")
        if sr is None:
            sr = s
            segments[0] = _silence(GAP_OPEN_S, sr)   # fix pre-roll to real sr
        segments.append(samples.astype(np.float32))
        chunks_synthed += 1

        # sentence gap (skip if the next unit is a paragraph break)
        next_is_pbreak = (i + 1 < len(units) and units[i + 1][0] == "paragraph_break")
        if not next_is_pbreak and i < len(units) - 1:
            segments.append(_silence(GAP_SENTENCE_S, sr))

    # Tail so the last word isn't clipped
    assert sr is not None
    segments.append(_silence(GAP_TAIL_S, sr))

    audio = np.concatenate(segments)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), audio, sr, format="MP3")

    return {
        "chunks_synthed": chunks_synthed,
        "duration_s": len(audio) / sr,
        "sample_rate": sr,
        "voice": voice,
    }


if __name__ == "__main__":
    # Smoke test: synthesize a two-paragraph briefing with a version number
    import sys
    sample = (
        "Gemini three point eight Flash launched in twenty twenty-six. "
        "The model runs at forty percent lower latency than three point five.\n\n"
        "Access remains free through the A. I. Studio interface. Developers "
        "get one thousand requests per day at no cost."
    )
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/tts-test.mp3")
    stats = synth(sample, out, "tech")
    print(f"wrote {out} — {stats}")
