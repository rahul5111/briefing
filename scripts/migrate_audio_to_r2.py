"""B-15 one-shot backfill: upload existing MP3s to Cloudflare R2.

Walks site/public/data/audio/ and site/public/data/blogs-audio/,
uploads each MP3 to R2 preserving the YYYY-MM-DD/xxx.mp3 (news) or
YYYY-MM/xxx.mp3 (blogs) key structure. Sets:
  Content-Type: audio/mpeg
  Cache-Control: public, max-age=31536000, immutable

Prereq env vars (all required):
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
  R2_BUCKET, R2_ENDPOINT

Idempotent — HEAD-checks each key before PUT. Existing objects with
matching Content-Length skip.

Usage:
  python scripts/migrate_audio_to_r2.py                # all
  python scripts/migrate_audio_to_r2.py --dry          # list only
  python scripts/migrate_audio_to_r2.py --limit 50     # cap
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIRS = [
    ROOT / "site" / "public" / "data" / "audio",
    ROOT / "site" / "public" / "data" / "blogs-audio",
]


def collect_files() -> list[tuple[Path, str]]:
    """Return list of (local_path, r2_key) tuples."""
    out: list[tuple[Path, str]] = []
    for base in SRC_DIRS:
        if not base.exists():
            continue
        for mp3 in sorted(base.rglob("*.mp3")):
            # R2 key: audio/YYYY-MM-DD/file.mp3 or blogs-audio/YYYY-MM/file.mp3
            rel = mp3.relative_to(ROOT / "site" / "public" / "data")
            out.append((mp3, str(rel)))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true",
                    help="List files, don't upload")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap at N files (0 = no limit)")
    args = ap.parse_args(argv)

    required = ["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET", "R2_ENDPOINT"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing and not args.dry:
        print(f"ERROR: missing env vars: {', '.join(missing)}", file=sys.stderr)
        print("Set them from the Cloudflare R2 dashboard before running.",
              file=sys.stderr)
        return 2

    files = collect_files()
    if args.limit:
        files = files[:args.limit]
    print(f"Found {len(files)} MP3 files to migrate.")

    if args.dry:
        for local, key in files[:20]:
            print(f"  {local}  →  {key}")
        if len(files) > 20:
            print(f"  ... and {len(files) - 20} more.")
        return 0

    try:
        import boto3
    except ImportError:
        print("ERROR: boto3 not installed. pip install boto3", file=sys.stderr)
        return 2

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    bucket = os.environ["R2_BUCKET"]

    uploaded = 0
    skipped = 0
    failed = 0
    for local, key in files:
        local_size = local.stat().st_size
        # Idempotency check.
        try:
            head = client.head_object(Bucket=bucket, Key=key)
            if int(head.get("ContentLength", 0)) == local_size:
                skipped += 1
                continue
        except Exception:
            pass  # object doesn't exist → proceed to upload

        try:
            client.upload_file(
                str(local),
                bucket,
                key,
                ExtraArgs={
                    "ContentType": "audio/mpeg",
                    "CacheControl": "public, max-age=31536000, immutable",
                },
            )
            # Verify.
            head = client.head_object(Bucket=bucket, Key=key)
            remote_size = int(head.get("ContentLength", 0))
            if remote_size == local_size:
                uploaded += 1
                if uploaded % 20 == 0:
                    print(f"  progress: {uploaded} uploaded, {skipped} skipped")
            else:
                print(f"  SIZE MISMATCH {key}: local={local_size} remote={remote_size}")
                failed += 1
        except Exception as e:
            print(f"  FAIL {key}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\nDone. uploaded={uploaded} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
