# Audio storage — cloud offload research

**Date:** 2026-09-14
**Author:** research memo, no code changes
**Scope:** decide where MP3s live so `.git` stops growing (currently 588 MB, +15–30 MB/day).

---

## Problem in one paragraph

Every cron run writes ~5–10 MB of MP3 into `site/public/data/audio/` and `blogs-audio/`, git commits it, retention prunes the working tree at 7/30 days, but **git history keeps every blob forever**. Repo growth is linear and unbounded. Serving is currently `PUBLIC_CDN_BASE` → jsDelivr mirror (piggybacking git), fallback `/data` (Vercel static). We want an object store the pipeline writes to and the site reads from — cheap, S3-compatible, and with a free egress path.

---

## Options

| Service | Free storage | Free egress | Paid price | Setup (hr) | S3 API | Maint risk | Fit |
|---|---|---|---|---|---|---|---|
| **Cloudflare R2** | 10 GB forever | **unlimited via CF CDN** | $0.015/GB/mo storage; ops free at 1M writes / 10M reads per mo | 1–2 | Yes | Low — mature, boto3 works | **Excellent** |
| **Backblaze B2** | 10 GB forever | free via CF Bandwidth Alliance (3× storage cap); else $0.01/GB | $0.006/GB/mo | 2–3 | Yes | Low | Very good |
| **Vercel Blob** | ~1 GB / 10 GB bw/mo | 10 GB/mo included | $0.023/GB storage, $0.05/GB egress after | 0.5 | No (proprietary SDK) | Low | Good for on-platform but tight limits |
| **AWS S3** | 5 GB, 12 mo only | 100 GB/mo out (12 mo) | $0.023/GB storage, **$0.09/GB egress** | 1–2 | Native | Low | Rule out — egress kills us |
| **GitHub LFS** | 1 GB / 1 GB bw/mo | $5 per 50 GB bw pack | $5 per 50 GB storage pack | 0.5 | No | Medium — throttling surprises | Rule out — egress economics awful, worst tier of all |
| **Vercel static (status quo)** | 100 GB deploy soft-cap | included in bw | n/a | 0 | n/a | **High** — repo already 588 MB, deploy tarball approaches limits | Broken at ~12 mo horizon |
| **Local + Cloudflare Tunnel** | free | free | $0 | 2–3 initial + ongoing | n/a | **Very high** — Mac uptime, ISP, wake-from-sleep | Rule out — single-user reliability floor is your laptop |

### Notes per service

- **R2:** Sign up cloudflare.com → R2 → create bucket → generate S3 credentials (Access Key + Secret). Point boto3 at `https://<accountid>.r2.cloudflarestorage.com`. Attach `audio.briefing.dev` (or reuse Vercel domain path) as a custom domain — CF serves objects with zero egress cost. Wrangler CLI optional; boto3 alone is sufficient for pipeline writes.
- **B2:** Same shape as R2 (S3-compat + custom domain). Slightly cheaper storage ($0.006 vs $0.015) but egress-free only if fronted by Cloudflare (Bandwidth Alliance). If you're using CF anyway the delta is a rounding error. R2 wins on operational simplicity — one vendor, one dashboard.
- **Vercel Blob:** Simplest to wire (`@vercel/blob` npm + `BLOB_READ_WRITE_TOKEN`). But 1 GB free is exhausted by month 2 at current growth, and $0.05/GB egress is 3× R2's zero.
- **LFS:** Both storage *and* bandwidth are metered. At 30 MB/day = ~11 GB/yr, you'd buy one 50 GB pack ($5/mo) for storage alone, plus another for egress once the site sees any traffic. Strictly dominated.

---

## Cold-start latency

The floating player triggers `<audio>` fetch on user tap. Target: first byte < 1 s (user's own stated tolerance). Measured expectations:

- **R2 via CF custom domain:** 50–150 ms TTFB globally. Meets bar comfortably.
- **B2 via CF:** identical once CF is in front.
- **Vercel Blob:** ~100–200 ms, edge-fronted. Fine.
- **S3 direct:** 200–500 ms depending on region. Fine but expensive.
- **Local tunnel:** 300 ms – 3 s + your Mac's uptime. Fails the reliability bar.

All shortlisted options meet the < 1 s bar. Latency is not the deciding factor; cost and egress posture are.

---

## Cost projection

Retention is 7 days news + 30 days blogs in working tree, **but object store retention is a policy we set independently**. Two models:

**Model A — keep everything forever (audit-friendly):**
- 30 MB/day × 365 = **~11 GB at 12 mo, ~5.5 GB at 6 mo**
- R2: still inside 10 GB free at 6 mo; $0.015 × 1 GB ≈ **$0.02/mo at 12 mo**. Effectively free.
- B2: same story, $0.006/mo. Free-tier boundary crossed at ~18 mo.
- Vercel Blob: **exceeds 1 GB free at ~5 weeks**. $0.023 × 10 GB ≈ $0.23/mo storage at 12 mo, plus egress. Not free-forever.

**Model B — mirror working-tree retention (7/30 days):**
- Steady state: ~200–300 MB total. Free tier on any provider, indefinitely.

**Recommendation:** Model B for R2. Keep a monthly cold-archive snapshot to a `archive/` prefix if we ever want the audit trail. Set a bucket lifecycle rule: `audio/` objects expire after 14 days, `blogs-audio/` after 45 days.

---

## Migration plan (backfill ~175 MB)

1. **Provision R2 bucket** `briefing-audio`, custom domain `audio.briefing.example` (or a path on the existing domain via CF Worker).
2. **One-shot upload script** (`scripts/migrate_audio_to_r2.py`): walks `site/public/data/audio/` and `blogs-audio/`, uploads preserving the `YYYY-MM-DD/*.mp3` key structure, sets `Content-Type: audio/mpeg`, `Cache-Control: public, max-age=31536000, immutable`.
3. **Set `PUBLIC_CDN_BASE=https://audio.briefing.example`** in Vercel env. Frontend already respects this — no code change needed beyond confirming URL joins work with the new base.
4. **Pipeline change** (later PR): TTS writer uploads to R2 alongside the local temp write; commit only the JSON (audio path stays a URL string).
5. **git history cleanup:** run `git filter-repo --path site/public/data/audio --path site/public/data/blogs-audio --invert-paths` on a mirror, force-push. Repo drops from 588 MB → ~30 MB. Do this **after** R2 is live and verified.
6. **`.gitignore` add:** `site/public/data/audio/`, `site/public/data/blogs-audio/`.

Frontend URL contract is unchanged because it already goes through `PUBLIC_CDN_BASE`. No app code touches.

---

## Fallback / degradation

If R2 is unreachable:

- Frontend `<audio>` `onError` should fall back to the jsDelivr mirror of the git repo (current `PUBLIC_CDN_BASE` default). During the transition window we keep that mirror populated.
- After git-history purge, jsDelivr is no longer viable. Long-term fallback: a nightly rclone sync from R2 to B2 as a warm replica; toggle `PUBLIC_CDN_BASE` if R2 has an incident. Cost: $0.006/GB/mo ≈ $0.02/mo at steady state.

---

## Ranking

1. **Cloudflare R2** — free egress via CF is the whole game; 10 GB free covers us for 12+ months at retention-pruned volume; S3-compatible so boto3 drop-in.
2. **Backblaze B2** (fronted by Cloudflare) — cheaper storage, functionally equivalent egress. Slightly more moving parts (two vendors).
3. **Vercel Blob** — least setup, on-platform, but the 1 GB free tier makes it a stopgap not a solution.

## Recommendation

**Adopt Cloudflare R2.** Rollout order: (1) provision bucket + custom domain, (2) run migration script, (3) flip `PUBLIC_CDN_BASE`, (4) verify one week of cron writes land in R2, (5) purge git history, (6) add B2 replica as fallback in month 2. Total setup: ~2 hours of focused work; ongoing cost <$0.05/mo through year one.
