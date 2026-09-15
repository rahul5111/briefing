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
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | **6 months** | Scoped IAM user (`briefing-service`) with S3-write only on the audio bucket. Rotate more aggressively than long-lived infra secrets. |
| `S3_BUCKET`, `S3_REGION`, `PUBLIC_CDN_BASE` | on infra change | Not sensitive but must stay in sync with the bucket. |

**Storage of secrets** — GitHub Actions and Vercel dashboards. Never
committed to the repo (`.gitignore` excludes `.env*`).

**Revocation procedure — S3 credentials leaked:**

1. AWS Console → IAM → Users → `briefing-service` → Security credentials.
2. Deactivate the leaked access key immediately.
3. Create a new access key for the same scoped IAM user.
4. Update **GitHub Actions** secrets first
   (`Settings → Secrets and variables → Actions`).
5. Update **Vercel** env second
   (`Project → Settings → Environment Variables`).
6. Trigger a manual GHA run to verify.
7. Delete the deactivated key once the new one is confirmed working.

**Revocation procedure — Gemini or Vercel token leaked:**

1. Regenerate at the provider console.
2. Update GHA secret. Update Vercel env.
3. Trigger a manual GHA run. Confirm the cron picks up the new value.

**Never** commit a secret. If a token appears in chat history or a
document (has happened twice with `VERCEL_TOKEN`), rotate immediately
even if the incident feels contained.

---

## §S3 — provisioning + backfill (B-11 / B-107 — S3 replaced R2 on 2026-09-15)

The bucket, scoped IAM user, and initial budget were provisioned
interactively in this session and their credentials are already in
GHA + Vercel secrets. Only step 7+ (backfill) is still pending owner
action.

**Bucket + IAM (already done — recorded here for rotation reference):**

- Bucket: `briefing-audio-f09f5061` (region: `us-east-1`).
- IAM user: `briefing-service` — S3-write on that bucket only. No
  console access. Access key stored in GHA + Vercel secrets.
- AWS Budget: $10/mo cap alarm on the account.
- Public read: bucket policy grants anonymous `s3:GetObject` on the
  audio prefix. Front-end fetches `PUBLIC_CDN_BASE` from Vercel env.

**Env vars (already set in GHA + Vercel Production):**

```
AWS_ACCESS_KEY_ID     = <scoped-briefing-service-key>
AWS_SECRET_ACCESS_KEY = <scoped-briefing-service-secret>
S3_BUCKET             = briefing-audio-f09f5061
S3_REGION             = us-east-1
PUBLIC_CDN_BASE       = https://briefing-audio-f09f5061.s3.amazonaws.com
```

**7. Backfill existing MP3s to S3** (owner-runnable — one-shot):

```bash
# Load creds from .env.local
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
       S3_BUCKET=briefing-audio-f09f5061 S3_REGION=us-east-1
python scripts/migrate_audio_to_s3.py --dry        # list what would upload
python scripts/migrate_audio_to_s3.py --limit 5    # smoke test 5 files
python scripts/migrate_audio_to_s3.py              # full backfill (~175 MB)
```

Idempotent — HEAD-checks each key first. Safe to re-run.

**8. Verify frontend playback** — refresh the site, pick a story, tap
play. Network tab should show requests going to
`briefing-audio-f09f5061.s3.amazonaws.com`. No 4xx.

**9. Watch for 14 days.** Every cron writes to S3 automatically via
`pipeline/storage.py`. Check `data/audits/s3_upload_failures-*.jsonl`
for any failures.

**10. B-90 git-history purge** — optional, opt-in, see
`docs/OPT-IN-OPERATIONS.md`. Only run when repo size is causing
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
| S3 upload failures | IAM key rotated or revoked, bucket policy changed, or network flake | Check `data/audits/s3_upload_failures-*.jsonl`. Rotate the `briefing-service` access key if 401/403. Local file stays; next cron retries. |
| Health render blank | `pipeline/health.py` raised | Look for `[health-render] failed` line in `latest.md`. Never propagates to workflow exit. |
| Vercel deploy fails | Token expired | Rotate `VERCEL_TOKEN`. Cadence: annually. |

---

## §Emergency shutdown

To pause the cron without editing the workflow:

1. GitHub → Actions → briefing-pipeline → `···` menu → Disable workflow.
2. Manual `workflow_dispatch` still works for debugging.

To resume: same menu → Enable workflow.
