# Briefing — Runbook

Owner-facing operational procedures. This is the file to grep when a
credential expires or a pipeline stage misbehaves.

Last updated: 2026-09-14.

---

## §Secrets — rotation policy + revocation

**Rotation cadence:**

| Secret | Cadence | Reason |
|---|---|---|
| `GEMINI_API_KEY` | 12 months | Used every cron; low blast radius (rate-limited by Google). |
| `VERCEL_TOKEN` | 12 months | The 2026-09-14 no-expiry token replaces the two prior tokens that expired. Still rotate annually. |
| `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | on org/project rename | Not secrets, but change when the project's identity changes. |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | **6 months** | R2 credentials grant public-write to the audio bucket. Rotate more aggressively. |
| `R2_BUCKET`, `R2_ENDPOINT`, `R2_PUBLIC_BASE`, `R2_ACCOUNT_ID` | on infra change | Not sensitive but must stay in sync with the bucket. |

**Storage of secrets** — GitHub Actions and Vercel dashboards. Never
committed to the repo (`.gitignore` excludes `.env*`).

**Revocation procedure — R2 credentials leaked:**

1. Log in to Cloudflare dashboard → R2 → Manage R2 API Tokens.
2. Revoke the leaked token immediately (before rotating anything else).
3. Generate a new token with the same scope (read+write on
   `briefing-audio` bucket).
4. Update **GitHub Actions** secret first
   (`Settings → Secrets and variables → Actions`).
5. Update **Vercel** env second
   (`Project → Settings → Environment Variables`).
6. Trigger a manual GHA run to verify.

**Revocation procedure — Gemini or Vercel token leaked:**

1. Regenerate at the provider console.
2. Update GHA secret. Update Vercel env.
3. Trigger a manual GHA run. Confirm the cron picks up the new value.

**Never** commit a secret. If a token appears in chat history or a
document (has happened twice with `VERCEL_TOKEN`), rotate immediately
even if the incident feels contained.

---

## §R2 — provisioning steps (B-11 prerequisite for B-12..B-19)

Do these once, in order. Owner-manual steps are marked ⚙.

**⚙ 1. Create the bucket.** cloudflare.com → R2 → Create bucket
`briefing-audio`. Region: automatic. No public access enabled at this
stage.

**⚙ 2. Generate S3 API credentials.** R2 → Manage R2 API Tokens →
Create API Token. Permissions: **Object Read & Write**. Scope: single
bucket `briefing-audio`. TTL: 6 months.

**⚙ 3. Note down four values from the token response:**
- Access Key ID
- Secret Access Key
- Account ID
- S3 endpoint URL (`https://<account-id>.r2.cloudflarestorage.com`)

**⚙ 4. Add secrets to GitHub Actions** (`Settings → Secrets and
variables → Actions → New repository secret`):

```
R2_ACCOUNT_ID       = <account-id>
R2_ACCESS_KEY_ID    = <access-key-id>
R2_SECRET_ACCESS_KEY = <secret>
R2_BUCKET           = briefing-audio
R2_ENDPOINT         = https://<account-id>.r2.cloudflarestorage.com
```

**⚙ 5. Add same to Vercel** (`Project → Settings → Environment
Variables`), all environments (Production + Preview + Development).
Plus one more:

```
R2_PUBLIC_BASE = https://<your-custom-domain>
```

Custom domain setup: R2 dashboard → bucket → Settings → Public access
→ Connect Domain. Point a CNAME from your DNS at the bucket. This
gives you unmetered egress via CF's CDN. Recommended domain:
`audio.briefing.<yourdomain>`.

**⚙ 6. Flip `PUBLIC_CDN_BASE` in Vercel env** to the same value as
`R2_PUBLIC_BASE`. Redeploy site.

**7. Test upload** (from local machine after credentials in a
`.env.local` you don't commit):

```bash
export R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_BUCKET=briefing-audio R2_ENDPOINT=https://...r2.cloudflarestorage.com
python scripts/migrate_audio_to_r2.py --dry     # lists files, no upload
python scripts/migrate_audio_to_r2.py --limit 5 # upload 5 files as smoke test
```

**8. Backfill full corpus:**

```bash
python scripts/migrate_audio_to_r2.py
```

Idempotent — reruns HEAD-check each key first. Safe to re-run.

**9. Verify frontend playback** — refresh the site, pick a story, tap
play. Network tab should show requests going to your custom R2 domain.
No 4xx.

**10. Watch for 14 days.** Every cron writes to R2 automatically via
`pipeline/storage.py`. Check `data/audits/r2_upload_failures-*.jsonl`
for any failures.

**11. B-90 git-history purge** — optional, opt-in, see
`docs/OPT-IN-OPERATIONS.md`. Only run when the 588 MB is causing
observable pain.

---

## §Kokoro model hash (B-14)

CI verifies `.models/*.onnx` against `.models/EXPECTED_HASHES.txt`. On
first successful GHA run, download the produced models locally and:

```bash
cd .models && sha256sum *.onnx > EXPECTED_HASHES.txt
# Commit EXPECTED_HASHES.txt only; not the .onnx files.
git add .models/EXPECTED_HASHES.txt && git commit -m "pin Kokoro model hashes"
```

Subsequent runs fail if the cached model hash drifts. This is deliberate.

If Kokoro releases a new version and we choose to adopt it:

```bash
# Update the model file, re-hash, commit new expected hashes.
rm .models/*.onnx
python -m pipeline.tts       # downloads current version
cd .models && sha256sum *.onnx > EXPECTED_HASHES.txt
git add .models/EXPECTED_HASHES.txt && git commit -m "adopt Kokoro model $NEW_VERSION"
```

---

## §Drift alarm (B-35) — informational only

`data/drift/YYYY-MM-DD.json` reports today's accept-rate + z-score vs.
7-day IQR. Statuses: `warmup` · `ok` · `warn` · `breach`.

**By design, drift never fails the workflow.** Scalar accept-rate has
5–15 % false-alarm rate baked in from calendar/weekend/source
variance. The value surfaces in `data/health/latest.md` as one line.

If drift shows `breach` for **3+ consecutive days**, that's genuine
signal — investigate: source-list change, silence.py breaking, LLM
outage returning empty verdicts, etc.

---

## §Golden set (B-36..B-69) — soft-fail workflow

`pipeline/eval/golden_set.jsonl` starts empty. Owner labels ~30 rows
as smoke-test baseline. `pipeline/eval/run_golden.py` reports
cat/band/decision agreement each run but does not fail the workflow.

When labels reach **n≥100 with per-category stratification** (see
BACKLOG B-68), the hard-fail gate flips on. Threshold at that point:
category-agreement ≥ 85 %, band-agreement ≥ 80 %, decision-agreement
≥ 90 %, all bootstrap-CI adjusted.

Any golden-set edit is a PR (B-08 blue-team response) with:
- justification for the label change,
- screenshot of `run_golden` output before and after.

This prevents "adjust golden until green."

---

## §Common cron failures

| Symptom | Likely cause | Fix |
|---|---|---|
| Push fails "non-fast-forward" | Local push landed between checkout and cron push | B-09 rebase-then-push should have fixed this. If it recurs, check whether an external actor is pushing to `main`. |
| Whisper OOM | `distil-large-v3` (post-B-20) uses more RAM than `tiny.en` | Reduce concurrency or downgrade to `medium.en`. |
| Kokoro hash mismatch | New Kokoro model release | Re-hash and commit `EXPECTED_HASHES.txt` per §Kokoro above. |
| R2 upload failures | Credentials expired, bucket policy changed, or network flake | Check `data/audits/r2_upload_failures-*.jsonl`. Rotate creds if 401/403. Local file stays; next cron retries. |
| Health render blank | `pipeline/health.py` raised | Look for `[health-render] failed` line in `latest.md`. Never propagates to workflow exit. |
| Vercel deploy fails | Token expired | Rotate `VERCEL_TOKEN`. Cadence: annually. |

---

## §Emergency shutdown

To pause the cron without editing the workflow:

1. GitHub → Actions → briefing-pipeline → `···` menu → Disable workflow.
2. Manual `workflow_dispatch` still works for debugging.

To resume: same menu → Enable workflow.
