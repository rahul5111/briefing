# Opt-in Operations

Procedures explicitly outside the default execution path. Owner-triggered
only.

---

## B-90 — Git history purge of legacy audio blobs

**Context.** Between the project's start and the R2 migration
(2026-09-14), MP3s were committed to git. `.git` grew to ~588 MB
before the `.gitignore` change stopped further growth. All new writes
now go to R2; git only stores JSON.

**The 588 MB of legacy blobs are still in git history.** This
procedure removes them.

**Do not run this unless the 588 MB is causing observable pain.**
Concrete triggers:

- Repository clones take > 30 seconds.
- GHA cache limits become a problem.
- A downstream mirror complains about repository size.

For a single-user product, none of these are actually painful yet.
`.gitignore` stops the growth; that's what matters most.

### Preconditions (all must be true before running)

- R2 has been serving audio for **≥ 14 consecutive days** with zero
  failures in `data/audits/r2_upload_failures-*.jsonl`.
- Pipeline has committed only JSON (no MP3) in that window. Verify:

  ```bash
  git log --since='14 days ago' --diff-filter=A -- 'site/public/data/**/*.mp3'
  # Expected: empty output.
  ```

- Cron is temporarily disabled (`Actions → Disable workflow`) to
  eliminate the concurrent-push race during the rewrite.
- A tag `pre-r2-purge` is pushed pointing at current `main` for
  90-day recovery access.
- A mirror clone exists at a separate remote path.
- Vercel's build cache has been cleared (Project → Settings → Build
  Cache → Clear Cache).
- No GHA action caches reference specific pre-purge SHAs:

  ```bash
  grep -rE 'checkout@.*ref:' .github/
  ```

  Expected: no hard-coded SHAs. If any exist, resolve first.

### Procedure

```bash
# 1. Snapshot recovery tag.
git tag pre-r2-purge && git push origin pre-r2-purge

# 2. Make a fresh mirror clone (safety net).
git clone --mirror . /tmp/briefing-mirror.git

# 3. Run filter-repo on a fresh working clone (NOT on your main clone).
cd /tmp
git clone <this-repo> briefing-purge && cd briefing-purge
pip install git-filter-repo
git filter-repo \
  --path site/public/data/audio \
  --path site/public/data/blogs-audio \
  --invert-paths

# 4. Verify size dropped:
du -sh .git    # expect ~30 MB (was ~588 MB)

# 5. Verify no MP3 references remain in latest:
git log --all --diff-filter=A -- 'site/public/data/**/*.mp3'
# Expected: empty.

# 6. Force-push to origin.
git remote add origin <origin-url>
git push --force origin main

# 7. IMPORTANT: run one end-to-end pipeline against the rewritten
#    history before proceeding. Trigger `workflow_dispatch` and verify:
#    - checkout succeeds
#    - pipeline runs to completion
#    - Vercel deploy succeeds against the rewritten history
```

### After successful purge

- **Delete the mirror only after 90 days.** It's your only recovery
  path if a downstream artefact broke.
- All working copies must re-clone. `git pull` on an existing clone
  will fail. Instruct any collaborators (n/a today, single-user).
- Historical PR commit URLs (github.com/…/commits/<sha>) break.
  Accepted trade-off for a single-user product.
- Re-enable cron (`Actions → Enable workflow`).

### Rollback

If anything unexpected breaks post-purge:

```bash
git push --force origin pre-r2-purge:main
```

That restores `main` to the pre-purge state. The 588 MB is back but the
repo is functional.

---

**No other opt-in operations at this time.** This file exists as a
holding pen for procedures that require explicit owner ceremony rather
than sitting in the routine backlog.
