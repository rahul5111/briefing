#!/bin/bash
# Copies ../data into public/data so Vercel picks up the audio at build time.
# Wired into the site's buildCommand — runs both locally and on Vercel.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf public/data
if [ -d ../data ]; then
  cp -R ../data public/data
  count=$(find public/data/audio -name '*.mp3' 2>/dev/null | wc -l | tr -d ' ')
  size=$(du -sh public/data | cut -f1)
  echo "synced ${count} audio files (${size}) into public/data/"
else
  mkdir -p public/data
  echo '{"stories":[]}' > public/data/feed.json
  echo "no ../data yet; wrote empty manifest"
fi
