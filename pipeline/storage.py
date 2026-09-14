"""B-16 Cloudflare R2 uploader with integrity check + fallback.

Post-synth flow:
  1. `synth()` writes MP3 to the local temp path (unchanged).
  2. `upload_r2(path, key)` puts the object to R2 with immutable
     Cache-Control + audio/mpeg Content-Type.
  3. Post-PUT integrity check: HEAD the same key + verify
     Content-Length matches the local file size.
  4. On mismatch, retry once. On second failure, log to
     data/audits/r2_upload_failures.jsonl and fall through — the local
     path stays valid so the manifest still points at a real file.

If R2 credentials are absent (typical before B-12 provisioning lands),
`upload_r2()` is a no-op that returns `(False, "no-credentials")`. This
keeps the pipeline runnable on developer machines and in the
transition window before R2 is live.
"""
from __future__ import annotations
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_DIR = _ROOT / "data" / "audits"


def _log_upload_failure(key: str, reason: str, local_size: int = 0,
                         remote_size: int = 0) -> None:
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        month = _dt.datetime.utcnow().strftime("%Y-%m")
        out = _AUDIT_DIR / f"r2_upload_failures-{month}.jsonl"
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
    """Return a boto3 S3 client configured for R2, or None if creds absent."""
    endpoint = os.environ.get("R2_ENDPOINT")
    ak = os.environ.get("R2_ACCESS_KEY_ID")
    sk = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (endpoint and ak and sk):
        return None
    try:
        import boto3
    except ImportError:
        return None
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        # R2 currently ignores region; boto3 requires it set.
        region_name="auto",
    )


def upload_r2(local_path: Path, key: str) -> tuple[bool, str]:
    """
    Upload `local_path` to R2 at `key`. Returns (success, message).

    Success case: ('True', 'ok'). Failure cases are logged to
    r2_upload_failures.jsonl and never raise. Caller is expected to
    keep the local file as fallback.
    """
    bucket = os.environ.get("R2_BUCKET", "briefing-audio")
    client = _client()
    if client is None:
        return (False, "no-credentials")

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
        # Retry once — sometimes R2's first PUT after a cold path is
        # flaky, and a second attempt succeeds.
        ok, msg, remote_size = _do_put_and_verify()

    if not ok:
        _log_upload_failure(key, msg, local_size, remote_size)
        return (False, msg)

    return (True, "ok")


def r2_key_for(audio_path: str) -> str:
    """
    Convert an audio manifest path (e.g. 'audio/2026-09-14/xyz.mp3')
    to the R2 object key. Currently a no-op — the manifest path shape
    IS the R2 key shape by design.
    """
    return audio_path
