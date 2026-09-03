import { lazy, Suspense, useEffect, useMemo, useRef, useState, useCallback } from "react";
import { AnimatePresence, motion } from "motion/react";

const Globe = lazy(() => import("./Globe"));

type Story = {
  id: string;
  title: string;
  summary: string;
  category: string;
  source?: string;
  source_url: string | null;
  source_domain: string;
  source_permalink?: string;
  hn_permalink?: string;
  hn_score?: number;
  score?: number;
  published_at: string;
  created_at_ts: number;
  audio_path: string;
  word_count: number;
  estimated_duration_s: number;
  image_url?: string | null;
  location?: { name: string; country: string; lat: number; lng: number } | null;
};

const CATEGORY_ORDER = ["ALL", "AI", "STARTUPS", "SECURITY", "DEV", "RESEARCH", "WORLD"];

type Props = { stories: Story[]; cdnBase: string };

function fmtDuration(s: number) {
  if (!isFinite(s) || s < 0) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function fmtTime(iso: string) {
  // Use fixed UTC formatting so SSR and client render identically.
  const d = new Date(iso);
  const h = String(d.getUTCHours()).padStart(2, "0");
  const m = String(d.getUTCMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}

function ageBucket(iso: string, now: number): "" | "aged" | "aged-more" {
  const ageH = (now - new Date(iso).getTime()) / 3600_000;
  if (ageH > 48) return "aged-more";
  if (ageH > 18) return "aged";
  return "";
}

const DAYS = ["SUN","MON","TUE","WED","THU","FRI","SAT"];
const DAYS_LONG = ["SUNDAY","MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY"];
const MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];

function groupByDay(stories: Story[]) {
  const groups: { label: string; items: Story[] }[] = [];
  let cur = "";
  for (const s of stories) {
    const d = new Date(s.published_at);
    const label = `${DAYS_LONG[d.getUTCDay()]}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
    if (label !== cur) { groups.push({ label, items: [] }); cur = label; }
    groups[groups.length - 1].items.push(s);
  }
  return groups;
}

/**
 * Draggable scrubber. Shows played-portion as amber fill, has a handle you
 * can drag along the track, click anywhere on the track to seek there.
 * Deliberately quiet — the signature moment is on the globe view now.
 */
function Scrubber({
  now,
  dur,
  onSeek,
}: {
  now: number;
  dur: number;
  onSeek: (t: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const [dragPct, setDragPct] = useState(0);

  const pct = dur > 0 ? Math.min(1, Math.max(0, now / dur)) : 0;
  const shownPct = dragging ? dragPct : pct;

  const pctFromEvent = useCallback((clientX: number) => {
    const el = trackRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  }, []);

  const beginDrag = (e: React.PointerEvent) => {
    if (!dur) return;
    (e.target as Element).setPointerCapture(e.pointerId);
    setDragging(true);
    setDragPct(pctFromEvent(e.clientX));
  };
  const moveDrag = (e: React.PointerEvent) => {
    if (!dragging) return;
    setDragPct(pctFromEvent(e.clientX));
  };
  const endDrag = (e: React.PointerEvent) => {
    if (!dragging) return;
    const p = pctFromEvent(e.clientX);
    setDragging(false);
    onSeek(p * dur);
  };

  return (
    <div
      ref={trackRef}
      className={`scrubber ${dragging ? "dragging" : ""} ${dur ? "" : "disabled"}`}
      onPointerDown={beginDrag}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      role="slider"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(shownPct * 100)}
      aria-label="Playback position"
    >
      <div className="scrubber-track" />
      <div className="scrubber-fill" style={{ width: `${shownPct * 100}%` }} />
      <div className="scrubber-handle" style={{ left: `${shownPct * 100}%` }} />
    </div>
  );
}

export default function Feed({ stories, cdnBase }: Props) {
  const [current, setCurrent] = useState<Story | null>(null);
  const [playing, setPlaying] = useState(false);
  const [now, setNow] = useState(0);
  const [dur, setDur] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const [activeCat, setActiveCat] = useState<string>("ALL");
  const [view, setView] = useState<"list" | "globe">("list");
  const [nowMs, setNowMs] = useState(() =>
    stories.length ? new Date(stories[0].published_at).getTime() : 0
  );
  useEffect(() => { setNowMs(Date.now()); }, []);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const seek = useCallback((t: number) => {
    const a = audioRef.current;
    if (!a || !isFinite(t)) return;
    a.currentTime = t;
    setNow(t);
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = { ALL: stories.length };
    for (const s of stories) c[s.category] = (c[s.category] || 0) + 1;
    return c;
  }, [stories]);

  const filtered = useMemo(
    () => (activeCat === "ALL" ? stories : stories.filter((s) => s.category === activeCat)),
    [stories, activeCat]
  );
  const grouped = useMemo(() => groupByDay(filtered), [filtered]);

  useEffect(() => {
    const a = audioRef.current;
    if (!a || !current) return;
    a.src = `${cdnBase}/${current.audio_path}`;
    a.play()
      .then(() => setPlaying(true))
      .catch(() => setPlaying(false));
  }, [current, cdnBase]);

  const onPlayClick = (s: Story) => {
    if (current?.id === s.id) {
      const a = audioRef.current!;
      if (playing) { a.pause(); setPlaying(false); }
      else { a.play(); setPlaying(true); }
    } else {
      setCurrent(s);
    }
  };

  const toggleOpen = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setOpenId(openId === id ? null : id);
  };

  if (stories.length === 0) {
    return <div className="empty">No stories yet · check back after the next run</div>;
  }

  return (
    <>
      <div className="controls-row">
        <nav className="tuner" aria-label="Categories">
          {CATEGORY_ORDER.filter((c) => c === "ALL" || counts[c]).map((c) => (
            <button
              key={c}
              type="button"
              className={`tuner-btn ${activeCat === c ? "active" : ""}`}
              onClick={() => setActiveCat(c)}
            >
              <span className="tuner-label">{c}</span>
              <span className="tuner-count">{counts[c] ?? 0}</span>
              {activeCat === c && (
                <motion.span
                  layoutId="tuner-underline"
                  className="tuner-underline"
                  transition={{ type: "spring", stiffness: 400, damping: 40 }}
                />
              )}
            </button>
          ))}
        </nav>
        <div className="view-toggle" role="tablist" aria-label="View">
          <button
            type="button"
            role="tab"
            aria-selected={view === "list"}
            className={view === "list" ? "active" : ""}
            onClick={() => setView("list")}
          >List</button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "globe"}
            className={view === "globe" ? "active" : ""}
            onClick={() => setView("globe")}
          >Globe</button>
        </div>
      </div>

      {view === "globe" && (
        <Suspense fallback={<div className="empty">Loading globe…</div>}>
          <Globe
            stories={filtered}
            playingId={current?.id ?? null}
            onSelect={(s) => setCurrent(s)}
          />
        </Suspense>
      )}

      {view === "list" && (
      <div className="feed">
        {grouped.map((g) => (
          <div key={g.label}>
            <div className="time-marker">{g.label}</div>
            {g.items.map((s) => (
              <article
                key={s.id}
                className={`card ${ageBucket(s.published_at, nowMs)} ${current?.id === s.id ? "playing" : ""}`}
                onClick={() => onPlayClick(s)}
              >
                <span className="cat">{s.category === "world" ? "WORLD" : "TECH"}</span>
                <div>
                  <h2>{s.title}</h2>
                  <div className="sub">
                    <span>{fmtTime(s.published_at)}</span>
                    <span aria-hidden="true">·</span>
                    <span>{s.source_domain}</span>
                    <span aria-hidden="true">·</span>
                    <a href={s.source_url || s.hn_permalink} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>source</a>
                    <span aria-hidden="true">·</span>
                    <a href="#" onClick={(e) => toggleOpen(s.id, e)}>
                      {openId === s.id ? "hide transcript" : "read transcript"}
                    </a>
                  </div>
                  <AnimatePresence initial={false}>
                    {openId === s.id && (
                      <motion.div
                        className="transcript"
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.22, ease: [0.2, 0, 0, 1] }}
                      >
                        {s.summary.split(/\n{2,}/).map((p, i) => (
                          <p key={i}>{p}</p>
                        ))}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
                <div className="duration">{fmtDuration(s.estimated_duration_s)}</div>
              </article>
            ))}
          </div>
        ))}
      </div>
      )}

      <div className={`player ${playing ? "playing" : ""} ${current ? "loaded" : "empty"}`} role="region" aria-label="Now playing">
        <button
          className="player-btn"
          onClick={() => {
            if (!current) return;
            const a = audioRef.current!;
            if (playing) { a.pause(); setPlaying(false); }
            else { a.play(); setPlaying(true); }
          }}
          disabled={!current}
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? "❚❚" : "▶"}
        </button>

        <div className="player-cover" aria-hidden="true">
          {current?.image_url ? (
            <img src={current.image_url} alt="" loading="lazy" />
          ) : (
            <div className="player-cover-fallback">
              {current ? (current.category?.[0] ?? "•") : "•"}
            </div>
          )}
        </div>

        <div className="player-body">
          <div className="player-title">
            {current ? current.title : "Select a story to play"}
          </div>
          <div className="player-meta">
            {current ? (
              <>
                <span>{current.source_domain || current.source}</span>
                <span aria-hidden="true">·</span>
                <span>{current.category}</span>
                <span aria-hidden="true">·</span>
                <a
                  href={current.source_url || current.source_permalink || current.hn_permalink || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="player-article-link"
                >
                  read full article ↗
                </a>
              </>
            ) : (
              <span>tap any story above to begin</span>
            )}
          </div>
          <Scrubber now={now} dur={dur || (current?.estimated_duration_s ?? 0)} onSeek={seek} />
        </div>

        <div className="player-time">
          <span className="player-time-cur">{fmtDuration(now)}</span>
          <span className="player-time-sep">/</span>
          <span className="player-time-total">
            {fmtDuration(dur || (current?.estimated_duration_s ?? 0))}
          </span>
        </div>

        <audio
          ref={audioRef}
          crossOrigin="anonymous"
          onTimeUpdate={(e) => setNow((e.target as HTMLAudioElement).currentTime)}
          onLoadedMetadata={(e) => setDur((e.target as HTMLAudioElement).duration)}
          onEnded={() => setPlaying(false)}
          preload="metadata"
        />
      </div>
    </>
  );
}
