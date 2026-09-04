"""Objective audio validation via Whisper round-trip.

Since I can't literally listen, I transcribe the generated MP3 back to text
with Whisper and diff against the input. If Whisper hears it clearly, a human
will too. If Whisper confuses a word, so will the listener.

Also analyzes silence structure: verifies real pauses exist between sentences
and no pause is longer than a natural paragraph break (a sign of trouble).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import soundfile as sf

from . import normalize as _norm


_whisper = None


def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        # tiny.en runs in ~5s on M-series CPU for 90s of audio
        _whisper = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    return _whisper


@dataclass
class SilenceStats:
    sentence_gaps: int              # number of gaps in [0.15, 0.45]s range
    paragraph_gaps: int             # number of gaps in [0.45, 1.0]s range
    suspicious_gaps: int            # gaps > 1.5s (possible truncation or model hiccup)
    total_silence_s: float
    longest_gap_s: float


@dataclass
class AudioValidation:
    duration_s: float
    input_words: int
    transcribed_words: int
    wer: float                      # word error rate 0.0 - 1.0+
    cer: float                      # character error rate
    transcript: str
    mismatched_words: list[tuple[str, str]]  # (input_word, transcribed_word) for the first 12 diffs
    silence: SilenceStats
    verdict: str                    # "good" | "acceptable" | "poor"
    notes: list[str]


def _normalize_for_diff(s: str) -> list[str]:
    """Lowercase, run through the same digit/abbrev normalizer that TTS input
    went through, strip punctuation, split into words.

    Whisper outputs "153 million" while our TTS input was "one hundred fifty-
    three million". Both need to end up as the same word list to fairly
    measure whether the audio matches the input.

    Extra: collapse runs of single-letter tokens ("k l two" or "n b a")
    into a single joined token ("kltwo", "nba") so Whisper's tendency to
    concatenate letter-spaced acronyms (e.g. "kl2" for "K L two") stops
    inflating WER against correctly-pronounced audio.
    """
    s = _norm.normalize(s)
    s = re.sub(r"[^\w\s']", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    tokens = s.split()

    # Collapse runs of >=2 single-character tokens into one joined token.
    # A "run" ends when we hit a token that is not single-char alnum.
    out: list[str] = []
    buf: list[str] = []
    def _flush() -> None:
        if not buf:
            return
        if len(buf) >= 2:
            out.append("".join(buf))       # k l two → kltwo
        else:
            out.extend(buf)                # bare single letters stay
        buf.clear()
    for tok in tokens:
        if len(tok) <= 2 and tok.isalnum():
            buf.append(tok)
        else:
            _flush()
            out.append(tok)
    _flush()
    return out


def _wer(ref: list[str], hyp: list[str]) -> tuple[float, list[tuple[str, str]]]:
    """Levenshtein-style WER + first N substitution pairs."""
    n, m = len(ref), len(hyp)
    if n == 0:
        return 1.0, []
    # DP table
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    # Backtrack for substitutions
    subs: list[tuple[str, str]] = []
    i, j = n, m
    while i > 0 and j > 0 and len(subs) < 12:
        if ref[i - 1] == hyp[j - 1]:
            i -= 1; j -= 1
        else:
            best = min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
            if best == dp[i - 1][j - 1]:
                subs.append((ref[i - 1], hyp[j - 1]))
                i -= 1; j -= 1
            elif best == dp[i - 1][j]:
                subs.append((ref[i - 1], "«deletion»"))
                i -= 1
            else:
                subs.append(("«insertion»", hyp[j - 1]))
                j -= 1
    return dp[n][m] / n, list(reversed(subs))


def _cer(ref: str, hyp: str) -> float:
    ref = re.sub(r"[^\w']", "", ref.lower())
    hyp = re.sub(r"[^\w']", "", hyp.lower())
    n, m = len(ref), len(hyp)
    if n == 0:
        return 1.0
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                cur[j] = prev[j - 1]
            else:
                cur[j] = 1 + min(prev[j], cur[j - 1], prev[j - 1])
        prev = cur
    return prev[m] / n


def _analyze_silence(audio_path: Path) -> SilenceStats:
    """Find gaps by looking for stretches of near-zero amplitude."""
    audio, sr = sf.read(str(audio_path))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    # Amplitude envelope in 20ms windows
    win = int(0.02 * sr)
    if win <= 0:
        return SilenceStats(0, 0, 0, 0.0, 0.0)
    n_windows = len(audio) // win
    envelope = np.array([
        np.abs(audio[i * win:(i + 1) * win]).mean() for i in range(n_windows)
    ])
    # Silence threshold: 1% of median amplitude of the non-silent parts
    speaking = envelope[envelope > envelope.mean() * 0.15]
    threshold = (speaking.mean() * 0.08) if len(speaking) else 0.001

    is_silent = envelope < threshold
    # Run-length encode silent stretches
    gaps: list[float] = []
    run = 0
    for s in is_silent:
        if s:
            run += 1
        else:
            if run > 0:
                gaps.append(run * 0.02)
            run = 0
    if run > 0:
        gaps.append(run * 0.02)

    # Drop leading/trailing silence bookends
    gaps = [g for g in gaps if g < 3.0]

    sentence_gaps = sum(1 for g in gaps if 0.15 <= g < 0.45)
    paragraph_gaps = sum(1 for g in gaps if 0.45 <= g < 1.0)
    suspicious_gaps = sum(1 for g in gaps if g >= 1.5)
    return SilenceStats(
        sentence_gaps=sentence_gaps,
        paragraph_gaps=paragraph_gaps,
        suspicious_gaps=suspicious_gaps,
        total_silence_s=sum(gaps),
        longest_gap_s=max(gaps) if gaps else 0.0,
    )


def validate(audio_path: Path, input_text: str) -> AudioValidation:
    model = _get_whisper()
    segments, info = model.transcribe(
        str(audio_path),
        language="en",
        beam_size=5,
        vad_filter=False,
    )
    transcript = " ".join(seg.text.strip() for seg in segments).strip()
    duration = info.duration

    ref_words = _normalize_for_diff(input_text)
    hyp_words = _normalize_for_diff(transcript)
    wer, subs = _wer(ref_words, hyp_words)
    cer = _cer(input_text, transcript)

    silence = _analyze_silence(audio_path)

    notes: list[str] = []
    if silence.sentence_gaps < 3:
        notes.append("very few sentence pauses detected — audio may run together")
    if silence.suspicious_gaps > 0:
        notes.append(f"{silence.suspicious_gaps} gap(s) over 1.5s — possible truncation or model hiccup")
    if silence.longest_gap_s > 2.5:
        notes.append(f"longest gap {silence.longest_gap_s:.1f}s is unnaturally long")

    expected_wpm = 145
    actual_wpm = len(ref_words) / (duration / 60) if duration > 0 else 0
    if actual_wpm > 180:
        notes.append(f"reading pace {actual_wpm:.0f} wpm is too fast (target 130-160)")
    if actual_wpm < 100:
        notes.append(f"reading pace {actual_wpm:.0f} wpm is too slow (target 130-160)")

    if wer < 0.10:
        verdict = "good"
    elif wer < 0.20:
        verdict = "acceptable"
    else:
        verdict = "poor"

    return AudioValidation(
        duration_s=round(duration, 1),
        input_words=len(ref_words),
        transcribed_words=len(hyp_words),
        wer=round(wer, 3),
        cer=round(cer, 3),
        transcript=transcript,
        mismatched_words=subs[:12],
        silence=silence,
        verdict=verdict,
        notes=notes,
    )
