"""Drop stories and audio files older than RETENTION_DAYS."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from . import config, manifest


def main() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.RETENTION_DAYS)
    data = manifest.load()
    keep: list[dict] = []
    dropped = 0
    for s in data.get("stories", []):
        pub = datetime.fromisoformat(s["published_at"])
        if pub < cutoff:
            audio = config.DATA_DIR / s["audio_path"]
            if audio.exists():
                audio.unlink()
            dropped += 1
        else:
            keep.append(s)
    data["stories"] = keep
    manifest.save(data)
    manifest.write_rss(data)
    print(f"Dropped {dropped} stories older than {config.RETENTION_DAYS} days.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
