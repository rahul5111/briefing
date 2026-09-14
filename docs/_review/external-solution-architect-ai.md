# External Review — Solution Architect, AI Engineering

**Reviewer role:** external Solution Architect brought in cold. Not looking to bless the design — looking for what breaks.

---

## 1. Overall verdict

Design is internally coherent after the red-team pass, but the evaluation layer it will lean on to decide "did this regress?" is too thin to arbitrate the model and voice changes it proposes. Ship the observability spine; do not ship the audio_rewrite upgrade, the sanity merge, or the voice sweep as hard-flips until the golden set, WER gate, and voice eval are strengthened.

---

## 2. Model-selection critique

**§4.3 audio_rewrite upgrade — wrong shortlist, wrong evaluation plan.** The design compares flash-lite → 2.5 flash → Haiku 4.5 → GPT-4.1-mini on cost + model-card intuition (`content-gen-optimization.md` §3). That is a shopping list. The task is dominated by numeric verbatim preservation and instruction-following under many format constraints — on both, Claude models empirically beat Gemini 2.5 flash for constraint-heavy structured rewrites. The memo calls flash-lite "empirically the weakest at preserving numbers verbatim" without data. The team is picking the next-cheapest model dressed as a quality decision.

**Skipping Sonnet 4.5 is a mistake.** At ~10.6k rewrites/mo × ~1k output tokens, Sonnet lands ~$60–80/mo — not much worse than Haiku's $49. If audio_rewrite is the stage the owner's ear grades, run it against the *ceiling* model as reference, then evaluate whether cheaper tiers suffice. The design uses flash-lite as reference and asks whether 2.5 flash is better — that under-samples the ceiling and cannot tell you what "good enough" is.

Before spending $20/mo more, I would demand: (1) a frozen 30-story eval set covering heavy numerics, acronyms, Indian/F1/German proper nouns, and quote-heavy copy — separate from the golden set; (2) rule-based scorers (numeric preservation via regex diff, acronym letter-spacing coverage, forbidden-punctuation count, sentence-length distribution, attribution presence); (3) LLM-as-judge, pairwise blinded, with a third model as judge to reduce self-preference bias; (4) A/B all four models — flash-lite, 2.5 flash, Haiku 4.5, Sonnet 4.5 — on the same set, reporting per-defect rates, not aggregate preference.

This is the weakest single argument in the design.

---

## 3. Evaluation methodology critique

**§7.2 golden set — 30 rows cannot arbitrate the proposed hard-fail thresholds.** Thresholds are cat ≥ 85%, band ≥ 80%, decision ≥ 90% at n=30. The 95% Wilson CI for a proportion near 0.85 at n=30 is roughly ±13pp. A run scoring 25/30 (83%) is statistically indistinguishable from 30/30. A single mislabelled row moves the pass/fail bit. The gate will either false-alarm on stochastic variance or be tuned so wide it misses real regressions — both worse than no gate.

Minimum viable: **n ≥ 100** rows for a hard gate; per-category stratification (8 categories × 2–3 rows makes INDIA regressions invisible); bootstrap CIs on agreement rates in the runner output; multi-seed evaluation (T=0.0 is not deterministic across server-side updates — run 3× and take mode); intra-annotator kappa (owner re-labels 30 rows a week apart; if κ < 0.8, widen thresholds).

**Use an eval framework.** `promptfoo` gives YAML test cases, rule + LLM-as-judge assertions, and dashboards for almost none of the code the team plans to write. `DeepEval` gives faithfulness / hallucination metrics that would catch the fact-drop failure mode the memo calls the biggest post-audio-rewrite risk. Hand-rolling a bespoke runner is defensible only if it saves work; I do not see how it does.

**LLM-as-judge for content quality is absent.** §10.3 says "manual review of 10 sampled stories per category" — that is a preference test, not an eval. If you spend $20/mo to improve prose, you need automated content-quality metrics: numeric fidelity (rule), fact coverage vs source (LLM-as-judge with rubric), spoken-form compliance (rule), readability sanity band. Without those, the merges and the model upgrade ship on vibes.

**§7.5 shadow rollout — pearson ≥ 0.6 is too loose.** Correlation of 0.6 admits a materially different scorer; individual rankings can shift substantially while the coefficient passes. Use Spearman ≥ 0.85 plus Kendall's τ ≥ 0.7 plus per-decile agreement. Pearson at 0.6 lets "a different animal" through.

---

## 4. Pipeline structure critique

**Merge A is fine post-fix. Merge B (§4.1 Phase 5b) is still wrong.** The blue team's gate is "same-call self_check catches ≥ 95% of external sanity flags." That is circular — you are validating one LLM checker against another LLM checker with the same blind spots. Baseline the sanity pass against a **rule-based linter** (regex for digits, unspaced-acronym patterns, sentence-length distribution, forbidden-punctuation count) before merging. Only then is 95% agreement meaningful.

**§4.5 DRAFT batching at N=8 — evidence is missing.** `response_schema` on flash-lite with a keyed list at ~50k input tokens is not free. Known failure modes: output-token truncation (8 × ~300 words drafts push ~3.2k output tokens close to typical caps if drafts trend long), partial-JSON corruption from one bad source poisoning downstream fields, key confusion when story_ids look similar. §10.4 "load test" verifies success only. Before shipping, run a **fuzz test**: inject malformed source in 1 of 8 stories × 100 batches; measure fallback recovery correctness. No data on flash-lite reliability at that shape and length is presented anywhere in the research memo.

**§4.2 provider protocol is over-engineered for one non-Gemini stage.** Ship the audio_rewrite model change as a direct Claude client call. Only extract the Protocol if a second stage moves off Gemini. The design ships the protocol first, in Phase 2, before the model change that motivates it — classic premature abstraction.

---

## 5. Prompt engineering critique

The existing prompts (§15 of the overview) are already unusually thoughtful — length tied to information density, negative constraints named because they empirically fail. Three real issues:

1. **DRAFT asks the model to make a length judgement** ("wire report ... 250–360"). Length-following is unreliable at flash-lite tier; this produces bimodal outputs at the band edges. Pass length as a deterministic parameter (source_words × 0.35, clamped) instead of asking the model to self-select.
2. **Positive-framing rewrite (§4.4) is under-argued.** "Models follow positive framing better" — cite one ablation. Negative constraints ("do NOT pad") activate refusal machinery on GPT-4-class models and often outperform positive framings on format-heavy rewrites. Flipping this without an A/B risks the exact AI-slop regression the current prompts prevent. And ship prompt changes *separately* from structural changes so regressions attribute correctly — not "alongside §4.1 merges" as proposed.
3. **AUDIO_REWRITE has no in-prompt example.** For format-heavy rewrites, one worked example ("$2.3B revenue" → "two point three billion dollars in revenue") reliably beats rule enumeration. Highest-ROI prompt change on the list; not in §4.4.

---

## 6. TTS quality gate critique

**§5.1 voice sweep is not an eval.** One rater, five voices, one story per category, forced pick — n=1 × n=1 per condition. Voice preference is highly item- and rater-dependent. Minimum: Likert MOS on ≥ 3 dimensions (naturalness, clarity, category fit); ≥ 3 stories per category × top-5 voices (~120 clips; still one evening); ≥ 2 raters (owner + one friend) since single-rater picks are unstable across days. Also: the proposed routing puts am_fenrir on four categories (SPORTS/US/INDIA/WORLD/BUSINESS), losing the per-category differentiation the design cites as a benefit — worth naming explicitly.

**Whisper `tiny.en` cannot arbitrate TTS changes.** Its WER floor on clean speech is ~8–12%. The pipeline sees p50=0.041, so transcriber noise dominates synthesiser noise. Two Kokoro voices differing by 1–2pp true intelligibility are invisible to `tiny.en`. Promote to **`medium.en` or `distil-large-v3`** and re-baseline before using WER to gate voice or model changes. This is the biggest gap in the audio quality-control story — the WER gate is a smoke alarm, not a scale.

**§5.3 Misaki IPA — vendor lock-in.** IPA overrides are Kokoro-specific; a Kokoro v1.1 with different G2P vocab invalidates every override, and the build-time linter does not survive an engine change (Chatterbox, XTTS). A **custom ARPAbet dictionary through `phonemizer`** is portable across engines at similar maintenance cost; name it as an alternative.

---

## 7. Missing considerations

1. **No model-version pinning strategy.** `google-genai` has changed `response_schema` semantics multiple times in the past year. Log the model version string on every call; run a weekly diff of pipeline outputs against a fixed input set. Silent server-side model updates are the single largest source of unexplained production regressions and the design does not address it.
2. **No inter-annotator agreement on the golden set.** See §3.
3. **No cost budget for eval.** LLM-as-judge on 100 rows × two shipped changes/week × Sonnet-tier judge is ~$5–10/mo — trivial, but budget it.
4. **Prompt-change regression surface not tested.** When §5.2 Step A allows em-dashes, downstream (`normalize.py`, `audio_validate.py`) regex may still assume dashes were stripped. Add characterisation tests over the prompt-change surface.
5. **Kokoro determinism assumption is unstated.** ONNX inference is deterministic; chunking is not. Any `normalize.py` change reshapes chunk boundaries and therefore audio bytes. Is WER compared on identical text inputs across runs, or across different normaliser outputs? The design should say.
6. **Significance rebuild lacks a canary set.** Shadow diff on all stories tells you correlation with incumbent, not correctness. A hand-labelled set of ~20 stories where desired ranking is known would let you evaluate rank quality directly.

---

## 8. What I would insist on before shipping

Non-negotiable, ordered:

1. **Expand golden set to n ≥ 100**, stratified per category, with bootstrap CIs in the runner. No hard-fail at n=30.
2. **Promote Whisper to `medium.en` or `distil-large-v3`** and re-baseline WER before any P0 audio change.
3. **Rule-based scorers for audio_rewrite** (numeric preservation, acronym coverage, forbidden-punctuation count). Gate model upgrade on those, not owner listening.
4. **Include Sonnet 4.5 in the bake-off** as ceiling reference. Decide flash-lite vs 2.5 flash vs Haiku *against* Sonnet, not against flash-lite.
5. **Structured voice eval**: ≥ 3 stories × top-5 voices × Likert MOS × ≥ 2 raters. Publish results in-repo.
6. **Do not ship Phase 5b (merged sanity)** without a rule-based sanity baseline. Current gate is circular.
7. **Adopt `promptfoo` or `DeepEval`** unless you can name a concrete reason the bespoke runner wins.
8. **DRAFT batching fuzz test** — malformed input in 1 of 8 × 100 batches; verify fallback correctness.
9. **Log LLM model version strings** on every call; weekly fixed-input diff to detect silent server-side updates.
10. **Ship prompt rewrites separately from structural merges** so regressions attribute correctly.

Where the design is right: the prompt-first-then-normaliser sequencing (§5.2 after R5), the honest corrected cost model (§14), the soft-fail-then-flip observability pattern (§11 after R13), and the R2 migration mirror-tag procedure are done well. The problem is not the changes; it is that the pipeline has no reliable way to *know* whether it got better after they ship. That is the layer the design underinvests in, and it is the reason the P0 items should wait behind the observability spine — not ship alongside it.
