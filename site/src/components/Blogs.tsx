import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { AnimatePresence, motion } from "motion/react";

type BlogEntry = {
  id: string;
  type: "blog";
  title: string;
  author: string;
  source: string;
  source_display: string;
  source_url: string;
  topics: string[];
  published_at: string;
  expires_at: string;
  reading_time_min: number;
  summary_short: string;
  summary_long: string;
  long_word_count: number;
  audio_path: string;
  audio_duration_s: number;
  image_url?: string | null;
};

type Props = { entries: BlogEntry[]; cdnBase: string };

function fmtDuration(s: number) {
  if (!isFinite(s) || s < 0) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function daysLeft(expiresAt: string): number {
  const ms = new Date(expiresAt).getTime() - Date.now();
  return Math.max(0, Math.round(ms / 86_400_000));
}

function clockFraction(publishedAt: string, expiresAt: string): number {
  const total = new Date(expiresAt).getTime() - new Date(publishedAt).getTime();
  const remaining = new Date(expiresAt).getTime() - Date.now();
  return Math.max(0, Math.min(1, remaining / total));
}

export default function Blogs({ entries, cdnBase }: Props) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [current, setCurrent] = useState<BlogEntry | null>(null);
  const [playing, setPlaying] = useState(false);
  const [now, setNow] = useState(0);
  const [dur, setDur] = useState(0);
  const [sortBy, setSortBy] = useState<"fresh" | "source">("fresh");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const sorted = useMemo(() => {
    const arr = [...entries];
    if (sortBy === "fresh") {
      arr.sort((a, b) => new Date(b.published_at).getTime() - new Date(a.published_at).getTime());
    } else {
      arr.sort((a, b) => a.source_display.localeCompare(b.source_display) || (new Date(b.published_at).getTime() - new Date(a.published_at).getTime()));
    }
    return arr;
  }, [entries, sortBy]);

  const bySource = useMemo(() => {
    if (sortBy !== "source") return null;
    const map = new Map<string, BlogEntry[]>();
    for (const e of sorted) {
      if (!map.has(e.source_display)) map.set(e.source_display, []);
      map.get(e.source_display)!.push(e);
    }
    return map;
  }, [sorted, sortBy]);

  const closePlayer = useCallback(() => {
    const a = audioRef.current;
    if (a) { a.pause(); a.currentTime = 0; }
    setPlaying(false);
    setNow(0);
    setDur(0);
    setCurrent(null);
  }, []);

  useEffect(() => {
    const a = audioRef.current;
    if (!a || !current) return;
    a.src = `${cdnBase}/${current.audio_path}`;
    a.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  }, [current, cdnBase]);

  useEffect(() => {
    if (!current) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePlayer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, closePlayer]);

  if (entries.length === 0) {
    return (
      <div className="empty-plate" role="status">
        <div className="empty-plate-serial">BLOGS / SHELF</div>
        <div className="empty-plate-body">No entries on the shelf yet.</div>
        <div className="empty-plate-note">
          The blog pipeline runs weekly and stocks the shelf with long-form
          engineering and AI writing. Each entry stays visible for a month, then
          rotates off.
        </div>
      </div>
    );
  }

  const renderCard = (e: BlogEntry) => {
    const remaining = daysLeft(e.expires_at);
    const frac = clockFraction(e.published_at, e.expires_at);
    return (
      <motion.article
        key={e.id}
        className={`blog-card ${openId === e.id ? "open" : ""}`}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
      >
        <button
          type="button"
          className="blog-card-head"
          onClick={() => setOpenId(openId === e.id ? null : e.id)}
          aria-expanded={openId === e.id}
        >
          <div className="blog-card-kicker">
            <span className="blog-source">{e.source_display}</span>
            <span className="blog-kicker-sep" aria-hidden="true">·</span>
            <span className="blog-author">{e.author}</span>
          </div>
          <h2 className="blog-title">{e.title}</h2>
          <div className="blog-meta">
            <span>{e.reading_time_min} min read</span>
            {e.audio_duration_s > 0 && (
              <>
                <span className="blog-meta-sep" aria-hidden="true">·</span>
                <span>{fmtDuration(e.audio_duration_s)} audio</span>
              </>
            )}
            <span className="blog-meta-sep" aria-hidden="true">·</span>
            <span className="blog-clock" title={`Rotates off in ${remaining} days`}>
              <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
                <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.35" />
                <path
                  d={arcPath(8, 8, 6.5, frac)}
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
              {remaining}d left
            </span>
          </div>
        </button>
        <AnimatePresence initial={false}>
          {openId === e.id && (
            <motion.div
              className="blog-body"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.28, ease: [0.2, 0, 0, 1] }}
            >
              <p className="blog-short">{e.summary_short}</p>
              <div className="blog-actions">
                {e.audio_duration_s > 0 && (
                  <button
                    type="button"
                    className="blog-action-primary"
                    onClick={() => setCurrent(e)}
                  >
                    ▶ Listen · {fmtDuration(e.audio_duration_s)}
                  </button>
                )}
                <a
                  href={e.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="blog-action-link"
                >
                  Read the original ↗
                </a>
              </div>
              <div className="blog-long">
                {e.summary_long.split(/\n{2,}/).map((p, i) => <p key={i}>{p}</p>)}
              </div>
              {e.topics.length > 0 && (
                <div className="blog-topics">
                  {e.topics.map((t) => <span key={t} className="blog-topic">{t}</span>)}
                </div>
              )}
              <a
                href={e.source_url}
                target="_blank"
                rel="noreferrer"
                className="blog-source-footer"
              >
                Continue at {e.source_display} ↗
              </a>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.article>
    );
  };

  return (
    <>
      <div className="blogs-toolbar">
        <div className="blogs-sort" role="tablist" aria-label="Sort blogs by">
          <button
            type="button"
            role="tab"
            aria-selected={sortBy === "fresh"}
            className={sortBy === "fresh" ? "active" : ""}
            onClick={() => setSortBy("fresh")}
          >Freshest</button>
          <button
            type="button"
            role="tab"
            aria-selected={sortBy === "source"}
            className={sortBy === "source" ? "active" : ""}
            onClick={() => setSortBy("source")}
          >By source</button>
        </div>
        <div className="blogs-count">{entries.length} on the shelf</div>
      </div>

      <div className="blogs-grid">
        {sortBy === "fresh" && sorted.map(renderCard)}
        {sortBy === "source" && bySource && [...bySource.entries()].map(([src, list]) => (
          <section key={src} className="blogs-source-group">
            <div className="blogs-source-head">
              <span className="blogs-source-name">{src}</span>
              <span className="blogs-source-count">{list.length} entr{list.length === 1 ? "y" : "ies"}</span>
            </div>
            {list.map(renderCard)}
          </section>
        ))}
      </div>

      <AnimatePresence>
        {current && (
          <motion.aside
            key="player"
            className={`player ${playing ? "playing" : ""}`}
            role="region"
            aria-label="Now playing"
            initial={{ y: 120, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 120, opacity: 0 }}
            transition={{ type: "spring", stiffness: 340, damping: 34 }}
          >
            <button
              className="player-btn"
              onClick={() => {
                const a = audioRef.current!;
                if (playing) { a.pause(); setPlaying(false); }
                else { a.play(); setPlaying(true); }
              }}
              aria-label={playing ? "Pause" : "Play"}
            >{playing ? "❚❚" : "▶"}</button>

            <div className="player-cover" aria-hidden="true">
              <div className="player-cover-fallback">📖</div>
            </div>

            <div className="player-body">
              <div className="player-title">{current.title}</div>
              <div className="player-meta">
                <span>{current.source_display}</span>
                <span aria-hidden="true">·</span>
                <span>{current.author}</span>
                <span aria-hidden="true">·</span>
                <a
                  href={current.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="player-article-link"
                >read the original ↗</a>
              </div>
              <div className="scrubber" role="slider" aria-valuemin={0} aria-valuemax={100}
                   aria-valuenow={Math.round((dur > 0 ? now / dur : 0) * 100)}
                   onClick={(e) => {
                     const r = e.currentTarget.getBoundingClientRect();
                     const p = (e.clientX - r.left) / r.width;
                     if (audioRef.current && dur) audioRef.current.currentTime = p * dur;
                   }}
              >
                <div className="scrubber-track" />
                <div className="scrubber-fill" style={{ width: `${(dur > 0 ? now / dur : 0) * 100}%` }} />
                <div className="scrubber-handle" style={{ left: `${(dur > 0 ? now / dur : 0) * 100}%` }} />
              </div>
            </div>

            <div className="player-time">
              <span className="player-time-cur">{fmtDuration(now)}</span>
              <span className="player-time-sep">/</span>
              <span className="player-time-total">{fmtDuration(dur || current.audio_duration_s)}</span>
            </div>

            <button
              className="player-close"
              onClick={closePlayer}
              aria-label="Close player"
            >✕</button>
          </motion.aside>
        )}
      </AnimatePresence>

      <audio
        ref={audioRef}
        crossOrigin="anonymous"
        onTimeUpdate={(e) => setNow((e.target as HTMLAudioElement).currentTime)}
        onLoadedMetadata={(e) => setDur((e.target as HTMLAudioElement).duration)}
        onEnded={() => setPlaying(false)}
        preload="metadata"
      />
    </>
  );
}

// Arc path from 12 o'clock, sweeping clockwise for `fraction` of the circle.
function arcPath(cx: number, cy: number, r: number, fraction: number): string {
  if (fraction >= 1) fraction = 0.9999;
  if (fraction <= 0) return `M ${cx} ${cy - r}`;
  const angle = fraction * 2 * Math.PI;
  const x = cx + r * Math.sin(angle);
  const y = cy - r * Math.cos(angle);
  const large = fraction > 0.5 ? 1 : 0;
  return `M ${cx} ${cy - r} A ${r} ${r} 0 ${large} 1 ${x} ${y}`;
}
