# B5 — Audio Quality / Prosody Research Memo

**Date:** 2026-09-14
**Scope:** research-only spike. No code changed. Constraint from owner: keep Kokoro-ONNX (local, free, deterministic). Goal: identify the highest-ROI moves to reduce the "robotic" feel without leaving Kokoro.

Current stack recap (see `docs/architecture-overview.md` §8): `kokoro-onnx v1.0`, three voices (`am_liam`, `am_michael`, `bm_george`), fixed 1.08× speed, `normalize.py` runs ~240 pronunciation rules + 60 letter-spaced acronyms before TTS, Whisper `tiny.en` round-trips at the end.

---

## 1. The full Kokoro-82M v1.0 voice catalogue (we've only tried 3 of ~20 English voices)

Kokoro v1.0 ships **~54 total voices** across 9 locales. English-relevant ones (`lang_code='a'` American, `'b'` British), with the quality grades Hexgrad publishes in [VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md):

**American male (`am_*`) — 9 voices:**
`am_adam` (F+), `am_echo` (D), `am_eric` (D), `am_fenrir` (C+, hours-trained), `am_liam` (D), `am_michael` (C+, hours-trained), `am_onyx` (D), `am_puck` (C+, hours-trained), `am_santa` (D-).

**American female (`af_*`) — 11 voices:** `af_heart` (A, top-graded), `af_bella` (A-), `af_nicole` (B-), `af_kore`/`af_aoede`/`af_sarah` (C+), plus C/D-tier variants.

**British male (`bm_*`) — 4 voices:** `bm_george` (C), `bm_fable` (C), `bm_lewis` (D+, hours-trained), `bm_daniel` (D).

**British female (`bf_*`) — 4 voices:** `bf_emma` (B-, hours-trained), `bf_isabella` (C), `bf_alice`/`bf_lily` (D).

Cross-referencing community rankings ([madeinoz67 voice-server quick-ref](https://madeinoz67.github.io/madeinoz-voice-server/VOICE_QUICK_REF/), [deAPI 41-voice guide](https://deapi.ai/blog/kokoro-tts-guide-how-to-control-41-voices-with-nothing-but-punctuation), [Soniqo](https://soniqo.audio/guides/kokoro)):

### Top 5 for news anchoring, ranked

| Rank | Voice | Tone (community) | Grade | Notes for our use |
|-----:|-------|------------------|-------|-------------------|
| 1 | `am_fenrir` | Deep, authoritative | **C+** (hours trained) | Same training tier as `am_michael`, gravitas warmer than `am_liam`. Best untried candidate for US/WORLD hard-news slot. |
| 2 | `am_puck` | Warm, expressive | **C+** (hours trained) | Higher expressive range than `am_liam`; good candidate for AI/TECH where `am_michael` currently sits, or as a second SPORTS voice. |
| 3 | `bm_fable` | Storyteller, warm | C | British-warm, "audiobook" cadence. Strong candidate for SCIENCE (replacing `bm_george`, which several reviews call flat). |
| 4 | `bf_emma` | Professional, warm | **B-** (hours trained) | Highest-graded British voice. Worth trying for SCIENCE or WORLD to break the all-male palette. |
| 5 | `af_heart` / `af_bella` | Warm, engaged | **A / A-** (top grades) | The only A-tier voices Kokoro ships. Not "news-anchor" defaults, but the objectively cleanest models — worth an A/B for BUSINESS or AI. |

Owner's current picks (`am_liam` D, `am_michael` C+, `bm_george` C) sit at the middle-to-bottom of the training-time distribution. Two of the three are D-grade — we are literally using undertrained voices when better-trained same-locale peers exist. **This is the largest single lever we're leaving on the table.**

## 2. SSML / prosody markup — the honest answer

**Kokoro does NOT parse SSML.** [remsky/Kokoro-FastAPI #396](https://github.com/remsky/Kokoro-FastAPI/issues/396) is an *open feature request*, not existing behaviour. `<break>`, `<prosody>`, `<emphasis>`, `<phoneme>` tags pass through as literal characters and get either ignored by the tokenizer or (worse) spoken. [deAPI](https://deapi.ai/blog/kokoro-tts-guide-how-to-control-41-voices-with-nothing-but-punctuation) confirms: emotion markers like `[happy]` and ALL CAPS are ignored.

**What Kokoro *does* respect is punctuation.** Documented mappings:

- `.` → full stop, intonation reset (~0.4s equivalent internally, before our 0.32s gap)
- `,` → short breath, sentence flow preserved
- `...` (ellipsis) → 0.5–1s trailing pause, falling intonation — **great for dramatic beats**
- `;` → medium pause, more than comma
- `:` → anticipatory pause ("introducing something")
- `?` → rising intonation
- `!` → higher energy (stacking doesn't scale volume)
- `—` (em-dash) → light parenthetical pause

**Actionable in `normalize.py`** (research only — not applied): the current normaliser strips or normalises several of these. We could *preserve* ellipses on lede sentences, use `:` before key numbers, and swap the final period of the last sentence for `...` to get the falling-outro cadence. Zero cost, deterministic, easily reverted.

**There is one *phoneme-level* override syntax that DOES work.** Misaki (Kokoro's G2P frontend) reads inline IPA inside markdown-link syntax: `[Kubernetes](/kuːbərˈnɛtiːz/)` or bare-slash `word /ipa/` ([Misaki repo](https://github.com/hexgrad/misaki), [HN thread](https://news.ycombinator.com/item?id=48821576)). IPA must use symbols from Kokoro's 178-token vocab — anything outside is silently dropped.

## 3. `phonemizer` / espeak-ng as OOV fallback

Kokoro's Misaki G2P *already* falls back to espeak-ng internally for OOV words, so re-piping through `phonemizer` externally is redundant. The higher-leverage move is to **replace regex substitutions in `PRONUNCIATION_MAP` with Misaki IPA overrides** for the ~20 names we get wrong most often (F1 drivers, Sanskrit terms, tech proper nouns). Trade-off: IPA is less maintainable than "Verstappen → fair-STAP-en", but it's phonetically exact and doesn't fight the model's phonotactics.

## 4. Paid providers — the opportunity cost, for reference only

| Provider | Cost | Latency (first byte) | Voices | Prosody / Emotion | Notes |
|---|---|---|---|---|---|
| **Kokoro-ONNX** (current) | **$0** | ~45ms on GPU, ~500ms CPU | 54 (20 EN) | Neutral, punctuation-driven | 82M params, fully local |
| ElevenLabs Multilingual v2 | $0.10 / 1K chars (~$0.60/min) | ~400ms | ~1000+ | High, controllable via voice settings | 29 languages |
| ElevenLabs v3 | $0.10 / 1K chars (~$0.60/min) | Non-realtime (multi-sec) | Same | **Audio Tags** for emotion, 68% fewer text errors, 70+ langs | Best-in-class prosody |
| OpenAI tts-1-hd | $0.030 / 1K chars (~$0.18/min) | 2–5s | 6 | Medium — natural but flat | Cheap but locked voice roster |
| Play.ht 3.0 | $0.0008–0.002 / 1K chars | Sub-300ms Turbo | Hundreds | High, long-form-stable | Cheapest paid; publishing platform bundled |
| Chatterbox (Resemble, self-host) | **$0** (MIT) | Slower first-token than Kokoro | Cloneable | Paralinguistic tags `[laugh]` `[cough]`, exaggeration knob | 8GB VRAM |

Approx daily briefing = ~15 min audio × 30/day = ~450 min/day. At ElevenLabs v3 rates that's ~$270/day, $8K/month. **The gap we're absorbing by staying on Kokoro is prosody expressiveness (subjective) and per-story emotional targeting (via ElevenLabs v3 Audio Tags) — not raw naturalness on measured audiobook narration.**

## 5. Coqui XTTS v2 self-hosted

MOS 4.1 vs Kokoro 3.9 ([TTSInsider comparison](https://www.ttsinsider.com/xtts-v2-vs-kokoro/), [LocalAIMaster](https://localaimaster.com/blog/kokoro-vs-xtts-vs-chatterbox)). XTTS handles conversational cadence and emotive delivery better, and can voice-clone from a 6s sample. Cost: **~7× slower first-token** (45ms → 320ms on RTX 5090), needs a GPU container (Kokoro runs on CPU-only in CI), Coqui the company is defunct so the library is community-maintained. Chatterbox is the more actively developed peer at the same tier. **Recommendation: not worth the infra step for the current setup's ~0.2-MOS delta.**

## 6. Recommended ROI ladder — Kokoro-only

1. **Voice sweep (highest ROI, ~2h work).** Generate the same 60-second briefing paragraph across all 9 `am_*`, 4 `bm_*`, and the top A-grade `af_heart` / `bf_emma`. Blind-listen. Almost certainly `am_liam` (D-grade) is worse than `am_fenrir` or `am_puck` (both C+). Update `VOICE_BY_CATEGORY` in `pipeline/tts.py`. Zero code churn beyond a dict.
2. **Preserve dramatic punctuation in `normalize.py` (cheap, ~1h).** Stop stripping ellipses; introduce `...` on the story's lede and outro. Use `:` before letter-spaced acronyms and key numbers. Em-dashes for parentheticals. All documented Kokoro-honoured behaviour.
3. **Inline IPA overrides for the top-20 chronic mispronunciations (~3h).** Migrate the worst offenders in `PRONUNCIATION_MAP` from regex-phonetic ("Koo-buh-NET-eez") to Misaki IPA (`[Kubernetes](/kuːbərˈnɛtɪz/)`). Keep the rest as-is — this is a 20/240 optimisation, not a full rewrite.
4. **Per-story voice selection (medium, ~1 day).** Extend the LLM refine step to output a `tone` field (e.g. `serious | breaking | analytical | light`) and route the story-level TTS voice off *that*, not just category. Combined with (1), gives natural variety within a segment.
5. **A/B a Chatterbox side-car for hero stories only (bigger, ~2 days).** If per-story voice + IPA + punctuation still doesn't clear the "robotic" bar, keep Kokoro as the volume renderer and route the top 1–2 stories/day through Chatterbox with paralinguistic tags. MIT licence, self-hosted, no per-minute cost.

Do **not** ship any of these blindly — the point of the memo is to establish that (1) and (2) are near-free and should ship first, and (3)–(5) get gated on a listening session with the owner.

---

**Sources:** [Kokoro-82M VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md), [kokoro-onnx repo](https://github.com/thewh1teagle/kokoro-onnx), [Misaki G2P](https://github.com/hexgrad/misaki), [Kokoro-FastAPI SSML issue](https://github.com/remsky/Kokoro-FastAPI/issues/396), [deAPI punctuation guide](https://deapi.ai/blog/kokoro-tts-guide-how-to-control-41-voices-with-nothing-but-punctuation), [Voice quick-ref](https://madeinoz67.github.io/madeinoz-voice-server/VOICE_QUICK_REF/), [Chatterbox](https://github.com/resemble-ai/chatterbox), [XTTS v2 vs Kokoro](https://www.ttsinsider.com/xtts-v2-vs-kokoro/), [ElevenLabs models](https://elevenlabs.io/docs/overview/models), [OpenAI TTS pricing](https://texttolab.com/blog/openai-tts-pricing), [Play.ht pricing](https://qcall.ai/play-ht-review).
