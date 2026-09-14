# Blue-team response — red-team-optimization-storage.md

Response to `red-team-optimization-storage.md`. Every red-team item is
addressed as **ACCEPTED (revised)**, **PARTIAL (documented trade-off)**,
or **REJECTED (defended)**.

---

| # | Red-team item | Response | How |
|---|---|---|---|
| R1 | Merge A conflates temperatures | **ACCEPTED** | §4.1 revised. Only merge `draft + stakes`; keep `distill` at T=0.0 separate. Saves 1 call, not 2. Original "~55% reduction" corrected to "~30% (P0), option to reach ~40% (P1) with empirical validation." |
| R2 | Merge B self-check blind spot | **ACCEPTED** | §4.1 revised. Split Merge B into Phase 5a (audio_text only) and Phase 5b (self_check consolidation, gated on empirical evidence that same-call catches ≥ 95% of external sanity flags). |
| R3 | Haiku cost off by 10× | **ACCEPTED (critical)** | §4.3 + §14 rewritten with corrected math. Gemini 2.5 flash ≈ +$20/mo, Haiku ≈ +$49/mo. Original "+$3–5" was wrong. Explicit owner-approval gate added. |
| R4 | Voice sweep leaves mixed-voice corpus | **PARTIAL (documented)** | §5.1 unchanged in-line but added trade-off note. Owner decision at Phase 3: (a) accept mixed corpus for 7 days until working-tree rotation, or (b) regenerate corpus (Kokoro is free). Recommended (a) — simpler. |
| R5 | Punctuation contradicts existing prompt | **ACCEPTED** | §5.2 completely rewritten. Prompt update (Step A) now precedes normalizer change (Step B) by one week. No mechanical punctuation-adding; normalizer only preserves what the LLM wrote. |
| R6 | git filter-repo gotchas | **ACCEPTED** | §6.2 step 8 expanded with explicit preconditions, procedure, rollback (via `pre-r2-purge` tag). RUNBOOK section required. |
| R7 | Drift alarm during sourcefix | **ACCEPTED** | §11 revised. Source-list fixes sequence BEFORE drift hard-fail flip. Drift stays in soft-fail mode across the transition. |
| R8 | Golden set lacks time-anchor | **ACCEPTED** | §7.2 schema now includes `label_asof`. Runner treats story as published-on-that-date. Golden-set maintenance runbook added (PR justification required for edits). |
| R9 | Observability self-failure | **ACCEPTED** | §7.3, §7.4 explicitly wrap in try/except with a `[<tool>] failed at <ts>` line. Same rule applies to drift.py, run_golden.py, wer_weekly.py. |
| R10 | WER history unbounded | **ACCEPTED** | §7.4 rewritten. Monthly-rotated (`data/audio_wer_history/YYYY-MM.jsonl`), 6-month in-repo retention, ~12 MB bounded. |
| R11 | R2 request-tier ceiling | **PARTIAL (documented)** | §14 adds the request-tier note. Not a concern at single-user; noted for future scale. No design change required. |
| R12 | R2 outage test missing | **ACCEPTED** | §10.5 added with 4 new tests including `test_r2_outage_recovery`, `test_dashboard_render_failure`, `test_drift_warmup`, `test_golden_soft_fail_first_week`. |
| R13 | Observability baseline vs later phases | **ACCEPTED** | §11 revised. All observability lands in soft-fail. Hard-fail flips per-tool after each subsequent phase re-establishes baseline. |
| R14 | LLMProvider Protocol lock-in | **PARTIAL (documented)** | §4.2 unchanged in shape but reviewer note added: Protocol is best-effort; each provider's structured-output path is provider-specific behind the same interface. Not a design flaw, an acknowledged abstraction leak. |
| R15 | IPA overrides need 14 days of WER | **ACCEPTED** | §5.3 gates on "at least 14 days of WER history exists." Sequencing explicit in §11 Phase 6. |
| R16 | Audio regression mitigation vague | **ACCEPTED** | §13 risk row on model regression revised: regression gate triggers regeneration of the 1-day cohort before flip. WER weekly's non-zero-exit is the trigger. |

## Rejected / not adopted

None. All 16 items either accepted (12) or partially accepted with a
documented trade-off (4).

## Delta summary applied to design doc

- §4.1 revised (Merges A, B split).
- §4.3 revised (cost math corrected).
- §5.2 revised (prompt-first ordering).
- §5.3 gate on 14 days WER.
- §6.2 step 8 expanded (purge RUNBOOK).
- §7.2 schema (`label_asof`).
- §7.3 self-failure guard.
- §7.4 monthly rotation + self-failure guard.
- §10.5 added (new test coverage).
- §11 revised (soft-fail transitions, sourcefix-before-drift).
- §13 risks (audio regression cohort regen).
- §14 cost model corrected.

## Ready for external panel

Design doc materially stronger after this pass. No open red-team items
require blocking before external review. Cost claim in particular went
from "–$1/mo" (wrong) to "+$18/mo, explicit owner approval required"
(honest). External reviewers should see the honest number, not the
optimistic one.
