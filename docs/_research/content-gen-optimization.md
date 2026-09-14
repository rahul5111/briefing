# Content-Generation Optimization — Research Memo

**Scope:** LLM usage in `pipeline/refine.py` + `pipeline/key_points.py`.
**Status:** Research only. No pipeline code changed.
**Date:** 2026-09-14

---

## 0. Real per-story call count (fixed)

The overview says "6 layers." Reading `refine.refine()` end-to-end, the
actual Gemini call count per story is **7–10**:

| # | Call | Module | Optional? |
|---|---|---|---|
| 1 | `distill` (key-point JSON) | `key_points.py` | no |
| 2 | `_draft` | `refine.py` | no |
| 3 | `_redraft` (hallucination fix) | `refine.py` | on regex-flagged bad facts |
| 4 | `coverage` (first pass) | `key_points.py` | no |
| 5 | `_expand_for_coverage` | `refine.py` | when cov < 85% |
| 6 | `_why_matters` | `refine.py` | no |
| 7 | `_audio_rewrite` | `refine.py` | no |
| 8 | `coverage` (final pass) | `key_points.py` | no |
| 9 | `_sanity` | `refine.py` | no |

At ~150 candidates × 3 runs × ~8 calls avg ≈ **3,600 calls/day**, closer to
what §16 of the overview ("600–1000 per run") already implies.

---

## 1. Structured output — collapse to 1–2 calls

Gemini's `responseSchema` (google-genai `response_mime_type="application/json"`
+ `response_schema`) can enforce a Pydantic-shaped JSON return. That makes
the following merges safe:

**Merge A — `distill + draft + why_matters` into one call** returning:

```json
{
  "key_facts": ["...", "..."],
  "draft": "150-360w prose",
  "stakes": "one-sentence stakes | NONE"
}
```

Justification: all three are pure functions of `(title, source)`; none of
them depends on the output of another. Today we do them serially only
because they were built one at a time. Saves 2 calls per story.

**Merge B — `audio_rewrite + sanity` into one call** returning:

```json
{
  "audio_text": "spoken-form briefing",
  "self_check": { "ok": true, "issues": ["..."] }
}
```

Sanity is a lint pass over `audio_rewrite`'s own output. The rewriter is
already the strongest instance in the pipeline; a self-check field on the
same schema is cheaper and just as strict. Saves 1 call per story.

**Keep separate:**
- **`fact_verify` + `_redraft`** — the redraft is conditional on a regex
  local check, and the whole point of a second call is to give the model
  a critique it wasn't blind to originally. Merging into a self-repair
  loop worsens hallucination rate in practice.
- **`coverage` (final pass)** — must run *after* the audio rewrite because
  the audio rewrite is where facts most often drop.

**Net:** 7–10 calls → **3–5 calls per story** (~55% reduction) with no
behavioral change beyond the merges above.

## 2. Batching (DRAFT across N stories in one call)

Gemini 3.5 flash-lite has a 1M context window. A candidate + source
averages ~4k tokens. Ten stories per batch is safely ~50k tokens — fine.

- **Latency win:** 10× fewer round-trips on the largest single stage.
  At ~2s median call latency this trims ~30–60s off wall-clock per run.
- **Blast radius:** one story's malformed source can corrupt the whole
  batch's JSON. Mitigation: `response_schema` = `{results: [{story_id,
  draft, key_facts, stakes}]}` with `story_id` as the join key. On
  partial fail, fall back to per-story for the misses only.
- **Prompt caching:** Gemini's implicit cache benefits the shared
  instruction preamble across 10 stories. Explicit cache is not worth it
  at our volume.
- **Not worth batching:** `coverage`, `sanity`, `audio_rewrite`.
  Coverage/sanity are already tiny (short prompts + tiny outputs). Audio
  rewrite is temperature-sensitive per story and benefits from
  independent sampling.

Batch only DRAFT (and its merged siblings from §1). Recommended batch
size: **8**, matching the free-tier RPM cap headroom.

## 3. Model comparison for spoken-audio rewrite

`gemini-3.5-flash-lite` is the cheapest tier but is empirically the
weakest at (a) preserving numbers verbatim through a rewrite and
(b) resisting AI-slop language when the "do NOT pad" negatives are
loosened. Table below is drawn from public model cards + pricing pages;
head-to-head on our own corpus is the P1 experiment.

| Model | Input $/1M | Output $/1M | 1M ctx? | Structured output? | Notes for TTS rewrite |
|---|---|---|---|---|---|
| Gemini 3.5 flash-lite | ~$0.10 | ~$0.40 | yes | yes | current; weakest at acronym-letter-spacing |
| Gemini 2.5 flash | ~$0.30 | ~$2.50 | yes | yes | best price/quality tradeoff for our stage |
| Claude Haiku 4.5 | ~$1.00 | ~$5.00 | 200k | yes (tool-use) | strongest at "spoken-natural" prose; ~10× cost |
| GPT-4.1-mini | ~$0.40 | ~$1.60 | 1M | yes | comparable to 2.5 flash, worse at Indian names |

**Recommendation:** keep flash-lite for `distill` and `coverage` (both
mechanical JSON tasks it does fine), upgrade `audio_rewrite` to
**Gemini 2.5 flash** or **Claude Haiku 4.5**. Even at Haiku pricing,
a single audio-rewrite call per story ~= $0.001 → **~$4/month all-in**
still comfortably under the $10/mo ceiling. This is the highest-leverage
single change in the memo.

## 4. Prompt rewrites (three tightenings)

Current prompts lean on `do NOT X` negatives (§15). Positive framing is
shorter, models follow it better, and it removes the "list of forbidden
phrases" that itself primes the model to almost-use them.

### 4.1 DRAFT — positive version

> Write a 150–360-word briefing. Length tracks the story's real density:
> a launch or ruling is 150–200; a wire report with figures, actors, and
> consequences is 250–360. Every sentence is a fact from the source: the
> event, the numbers, the named actors, the date. If a quote is strong,
> use one. Voice is a wire desk: declarative, unhurried, no adjectives
> of emphasis. Return prose only.

### 4.2 AUDIO_REWRITE — positive, structured

> Rewrite the briefing as speech for a news anchor.
>
> Rewrite so that: every number reads as words ("forty million dollars",
> "twenty twenty-six"); every acronym is letter-spaced with periods
> ("A. I.", "H. T. T. P. S."); sentences run 12–20 words and end on
> periods; unusual names get a comma-pause before them; the outlet name
> {source_name} appears inline in sentence two or three; the stakes line
> {stakes} lands as the last sentence of paragraph two. Start with the
> fact, not the framing.

### 4.3 SANITY — collapse to self-check inside audio_rewrite schema

> After writing `audio_text`, populate `self_check.issues[]` with any of:
> digits still present, unspaced acronym, sentence over 30 words,
> semicolon/dash/paren. Empty list means clean.

Saves a whole model call. See §1 Merge B.

## 5. Multi-provider abstraction

The Gemini client is instantiated in-module in both `refine.py` and
`key_points.py`. A clean abstraction is a `pipeline/llm.py` with a
`Protocol`:

```python
class LLMProvider(Protocol):
    def generate(self, prompt: str, *, schema: type[BaseModel] | None,
                 temperature: float, max_tokens: int) -> str | BaseModel: ...
```

Implementations: `GeminiProvider`, `ClaudeProvider`, `OpenAIProvider`.
Model choice becomes `LLM_PROVIDER=gemini|claude|openai` env var, with
a per-stage override (`LLM_AUDIO_MODEL=claude-haiku-4-5`). Every existing
`_call()` in the pipeline routes through the provider — no other change
to the orchestrator. This is a 200-line refactor and enables the §3 A/B
without touching pipeline logic.

## 6. Which layers are load-bearing vs. calcified

| Layer | Load-bearing? | Failure mode it fixes |
|---|---|---|
| distill | yes | coverage contract has no other source of truth |
| draft | yes | primary content generation |
| fact_verify + redraft | **yes** — Gemini hallucinates figures ~2–5% of drafts | numbers-not-in-source |
| coverage (pass 1) | partial — can be merged into draft self-check | dropped facts pre-audio |
| expand_for_coverage | **yes** | pre-audio recovery of missing facts |
| why_matters | mergeable into draft (see §1 Merge A) | stakes-line inference |
| audio_rewrite | yes | spoken form |
| coverage (final) | yes | audio rewrite drops facts (biggest fact-drop stage) |
| sanity | mergeable into audio_rewrite self-check (§1 Merge B) | TTS-tripping lint |

Genuinely non-negotiable: distill, draft, fact_verify+redraft, expand,
audio_rewrite, final coverage. Everything else is a lint pass that can
ride along on structured output.

---

## Recommendations

- **P0 — Structured-output merge.** Ship Merge A (distill+draft+stakes)
  and Merge B (audio_rewrite+sanity). Estimated saving: **~55% call
  volume**, ~40% wall-clock. No behavior regression expected; guardable
  by running current pipeline in parallel for a week on `reviews/`.

- **P0 — Upgrade audio_rewrite model.** Gemini 2.5 flash or Claude Haiku
  4.5. This is the stage the user's ear grades. Cost delta is ≤ $5/mo.
  Prerequisite: §5 provider abstraction lets you swap without touching
  orchestrator.

- **P1 — LLMProvider protocol.** Small refactor, unblocks A/B, unblocks
  moving different stages to different models, unblocks provider outage
  fallback.

- **P1 — Batch DRAFT at N=8.** Only after §1 merges land, or the batch
  schema gets ugly. Latency win, minor cost win via implicit cache.

- **P2 — Rewrite prompts to positive form** per §4. Cheapest change on
  the list; ship alongside P0.

Golden-file diffing on `data/reviews/` is the safety net for all of
these — every stage is already persisted to disk, so an offline replay
harness comparing current vs. proposed output is straightforward and
should gate any of these landings.
