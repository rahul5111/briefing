"""B-16 / B-107 AWS S3 uploader with integrity check + fail-soft.

Post-synth flow:
  1. `synth()` writes MP3 to the local temp path (unchanged).
  2. `upload_s3(path, key)` puts the object to S3 with immutable
     Cache-Control + audio/mpeg Content-Type.
  3. Post-PUT integrity check: HEAD the same key + verify
     Content-Length matches the local file size.
  4. On mismatch, retry once. On second failure, log to
     data/audits/s3_upload_failures-YYYY-MM.jsonl and fall through —
     the local path stays valid so the manifest still points at a real
     file.

If S3 credentials are absent, `upload_s3()` is a no-op that returns
`(False, "no-credentials")`. This keeps the pipeline runnable on
developer machines and while owner action on secrets is pending.

Env vars (matching the GHA + Vercel secrets shipped in this session):
  S3_BUCKET             — bucket name (default: briefing-audio-f09f5061)
  S3_REGION             — AWS region  (default: us-east-1)
  AWS_ACCESS_KEY_ID     — scoped IAM user access key
  AWS_SECRET_ACCESS_KEY — scoped IAM user secret

Legacy R2 aliases still work for a transition window; the R2 code path
was removed on 2026-09-15 after S3 was chosen as the audio backend.
"""
from __future__ import annotations
import datetime as _dt
import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_DIR = _ROOT / "data" / "audits"


def _log_upload_failure(key: str, reason: str, local_size: int = 0,
                         remote_size: int = 0) -> None:
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        month = _dt.datetime.utcnow().strftime("%Y-%m")
        out = _AUDIT_DIR / f"s3_upload_failures-{month}.jsonl"
        row = {
            "ts": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "key": key,
            "reason": reason,
            "local_size": local_size,
            "remote_size": remote_size,
        }
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def _client():
    """Return a boto3 S3 client, or None if creds absent."""
    ak = os.environ.get("AWS_ACCESS_KEY_ID")
    sk = os.environ.get("AWS_SECRET_ACCESS_KEY")
    region = os.environ.get("S3_REGION", "us-east-1")
    if not (ak and sk):
        return None
    try:
        import boto3
    except ImportError:
        return None
    return boto3.client(
        "s3",
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        region_name=region,
    )


def _bucket() -> str:
    return os.environ.get("S3_BUCKET", "briefing-audio-f09f5061")


def upload_s3(local_path: Path, key: str) -> tuple[bool, str]:
    """
    Upload `local_path` to S3 at `key`. Returns (success, message).

    Success case: (True, 'ok'). Failure cases are logged to
    s3_upload_failures-YYYY-MM.jsonl and never raise. Caller is expected
    to keep the local file as fallback.
    """
    client = _client()
    if client is None:
        return (False, "no-credentials")
    bucket = _bucket()

    local_size = 0
    try:
        local_size = local_path.stat().st_size
    except Exception:
        _log_upload_failure(key, "local_stat_failed")
        return (False, "local-stat-failed")

    def _do_put_and_verify() -> tuple[bool, str, int]:
        try:
            client.upload_file(
                str(local_path),
                bucket,
                key,
                ExtraArgs={
                    "ContentType": "audio/mpeg",
                    "CacheControl": "public, max-age=31536000, immutable",
                },
            )
        except Exception as e:
            return (False, f"put_failed_{type(e).__name__}", 0)
        try:
            head = client.head_object(Bucket=bucket, Key=key)
        except Exception as e:
            return (False, f"head_failed_{type(e).__name__}", 0)
        remote_size = int(head.get("ContentLength", 0))
        if remote_size != local_size:
            return (False, "size_mismatch", remote_size)
        return (True, "ok", remote_size)

    ok, msg, remote_size = _do_put_and_verify()
    if not ok:
        # Retry once — a transient PUT sometimes recovers on second try.
        ok, msg, remote_size = _do_put_and_verify()

    if not ok:
        _log_upload_failure(key, msg, local_size, remote_size)
        return (False, msg)

    return (True, "ok")


def s3_key_for(audio_path: str) -> str:
    """
    Convert an audio manifest path (e.g. 'audio/2026-09-14/xyz.mp3')
    to the S3 object key. Currently a no-op — the manifest path shape
    IS the S3 key shape by design.
    """
    return audio_path


# Back-compat shims for callers that still use the R2 names.
upload_r2 = upload_s3
r2_key_for = s3_key_for
