import { lazy, Suspense, useEffect, useMemo, useRef, useState, useCallback } from "react";
import { AnimatePresence, motion } from "motion/react";
import AbstractCover from "./AbstractCover";

const Globe = lazy(() => import("./Globe"));

type StoryRef = { name: string; url: string | null; domain: string; added_at: string };

type Story = {
  id: string;
  title: string;
  summary: string;
  // Legacy single-string category (kept as fallback).
  category: string;
  // PLAN A2 — canonical taxonomy fields.
  main?: string;
  sub?: string;
  subcategory?: string;
  sources?: StoryRef[];
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

// PLAN.md § 1 — locked 8-cat taxonomy. Displayed left-to-right.
// Legacy stories (with old cats AI/STARTUPS/DEV/SECURITY/RESEARCH/WORLD) are
// bucketed via LEGACY_TO_MAIN.
const MAIN_CATEGORIES = ["AI", "TECH", "SCIENCE", "SPORTS", "US", "INDIA", "WORLD", "BUSINESS"];

// Subcategory taxonomy mirrors pipeline/categorize.py (PLAN.md § 1).
const SUB_BY_MAIN: Record<string, string[]> = {
  AI: ["Models & Research", "Products & Tools", "Infrastructure", "Policy & Safety", "Industry"],
  TECH: ["Software & Open Source", "Startups", "Consumer Tech", "Enterprise & Cloud", "Security & Privacy", "Gaming"],
  SCIENCE: ["Space & Physics", "Biology & Medicine", "Climate & Environment", "Materials & Chemistry", "Engineering & Robotics", "Awards & Patents"],
  SPORTS: ["Major Events", "Badminton", "Track & Field", "Cricket", "Tennis", "Cycling", "Boxing & MMA", "Marathons & Endurance", "Motorsport", "Soccer", "Basketball", "Golf", "Other"],
  US: ["Politics", "Economy", "Law & Courts", "Health", "Disasters", "Policy Changes", "Society"],
  INDIA: ["Politics", "Economy", "Law & Courts", "Health", "Disasters", "Policy Changes", "Society", "Foreign Relations"],
  WORLD: ["Politics & Elections", "Conflict & Security", "Economy & Trade", "Climate & Disasters", "Society & Culture", "Health & Public Policy"],
  BUSINESS: ["M&A & Deals", "Markets & IPOs", "Leadership & Layoffs", "Finance & Fintech", "Antitrust & Regulation", "Retail & Consumer"],
};

const LEGACY_TO_MAIN: Record<string, string> = {
  AI: "AI",
  STARTUPS: "TECH",
  DEV: "TECH",
  SECURITY: "TECH",
  RESEARCH: "SCIENCE",
  WORLD: "WORLD",
};

function mainCategoryOf(s: Story): string {
  // Prefer the canonical field when the classifier has been re-run.
  const raw = s.main ?? s.category;
  if (!raw) return "WORLD";
  const upper = raw.toUpperCase();
  if (MAIN_CATEGORIES.includes(upper)) return upper;
  return LEGACY_TO_MAIN[upper] ?? "WORLD";
}

function subCategoryOf(s: Story): string | null {
  return s.sub ?? s.subcategory ?? null;
}

type Props = { stories: Story[]; cdnBase: string };

function fmtDuration(s: number) {
  if (!isFinite(s) || s < 0) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function fmtTime(iso: string) {
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

const DAYS_LONG = ["SUNDAY","MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY"];
const MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];

function groupByDay(stories: Story[]) {
  const byLabel = new Map<string, Story[]>();
  const order: string[] = [];
  for (const s of stories) {
    const d = new Date(s.published_at);
    const label = `${DAYS_LONG[d.getUTCDay()]}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
    if (!byLabel.has(label)) {
      byLabel.set(label, []);
      order.push(label);
    }
    byLabel.get(label)!.push(s);
  }
  return order.map((label) => ({ label, items: byLabel.get(label)! }));
}

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
  const [activeSub, setActiveSub] = useState<string | null>(null);
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

  const closePlayer = useCallback(() => {
    const a = audioRef.current;
    if (a) { a.pause(); a.currentTime = 0; }
    setPlaying(false);
    setNow(0);
    setDur(0);
    setCurrent(null);
  }, []);

  // Count per main-cat (bucketing legacy stories).
  const counts = useMemo(() => {
    const c: Record<string, number> = { ALL: stories.length };
    for (const s of stories) {
      const main = mainCategoryOf(s);
      c[main] = (c[main] || 0) + 1;
    }
    return c;
  }, [stories]);

  const filtered = useMemo(
    () => {
      let out = activeCat === "ALL" ? stories : stories.filter((s) => mainCategoryOf(s) === activeCat);
      if (activeSub) out = out.filter((s) => subCategoryOf(s) === activeSub);
      return out;
    },
    [stories, activeCat, activeSub]
  );
  const grouped = useMemo(() => groupByDay(filtered), [filtered]);

  // Sub-counts within the currently-active main tab.
  const subCounts = useMemo(() => {
    if (activeCat === "ALL") return {} as Record<string, number>;
    const c: Record<string, number> = {};
    for (const s of stories) {
      if (mainCategoryOf(s) !== activeCat) continue;
      const sub = subCategoryOf(s);
      if (!sub) continue;
      c[sub] = (c[sub] || 0) + 1;
    }
    return c;
  }, [stories, activeCat]);

  useEffect(() => {
    const a = audioRef.current;
    if (!a || !current) return;
    a.src = `${cdnBase}/${current.audio_path}`;
    a.play()
      .then(() => setPlaying(true))
      .catch(() => setPlaying(false));
  }, [current, cdnBase]);

  // ESC closes the player.
  useEffect(() => {
    if (!current) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePlayer();
      if (e.key === " " && e.target === document.body) {
        e.preventDefault();
        const a = audioRef.current!;
        if (playing) { a.pause(); setPlaying(false); }
        else { a.play(); setPlaying(true); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, playing, closePlayer]);

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

  const visibleCats = ["ALL", ...MAIN_CATEGORIES.filter((c) => (counts[c] ?? 0) > 0)];

  return (
    <>
      <div className={`controls-row ${current ? "with-player" : ""}`}>
        <nav className="tuner" aria-label="Categories">
          {visibleCats.map((c) => (
            <button
              key={c}
              type="button"
              className={`tuner-btn ${activeCat === c ? "active" : ""}`}
              onClick={() => { setActiveCat(c); setActiveSub(null); }}
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

      {activeCat !== "ALL" && (SUB_BY_MAIN[activeCat]?.some((s) => (subCounts[s] ?? 0) > 0)) && (
        <nav className="sub-strip" aria-label={`${activeCat} subcategories`}>
          <button
            type="button"
            className={`sub-chip ${activeSub === null ? "active" : ""}`}
            onClick={() => setActiveSub(null)}
          >
            All <span className="sub-chip-count">{filtered.length}</span>
          </button>
          {SUB_BY_MAIN[activeCat].filter((s) => (subCounts[s] ?? 0) > 0).map((s) => (
            <button
              key={s}
              type="button"
              className={`sub-chip ${activeSub === s ? "active" : ""}`}
              onClick={() => setActiveSub(activeSub === s ? null : s)}
            >
              {s} <span className="sub-chip-count">{subCounts[s]}</span>
            </button>
          ))}
        </nav>
      )}

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
          <section key={g.label} className="day-group">
            <div className="day-header">
              <span className="day-label">{g.label.toLowerCase().replace(/(^|\s)\S/g, l => l.toUpperCase())}</span>
              <span className="day-count">{g.items.length} stories</span>
            </div>
            <div className="card-grid">
              {g.items.map((s, i) => (
                <motion.article
                  key={s.id}
                  className={`card ${ageBucket(s.published_at, nowMs)} ${current?.id === s.id ? "playing" : ""} ${i === 0 ? "featured" : ""}`}
                  onClick={() => onPlayClick(s)}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.35, delay: Math.min(i, 12) * 0.025, ease: [0.16, 1, 0.3, 1] }}
                >
                  <div className="card-cover">
                    {s.image_url ? (
                      <img src={s.image_url} alt="" loading="lazy" />
                    ) : (
                      <AbstractCover
                        storyId={s.id}
                        category={s.category}
                        sourceDomain={s.source_domain || s.source}
                        variant={i === 0 ? "featured" : "card"}
                      />
                    )}
                    <div className="card-cover-play" aria-hidden="true">
                      {current?.id === s.id && playing ? "❚❚" : "▶"}
                    </div>
                  </div>
                  <div className="card-meta">
                    <div className="card-kicker">
                      <span className="cat">{mainCategoryOf(s)}</span>
                      {subCategoryOf(s) && (
                        <span className="sub">{subCategoryOf(s)}</span>
                      )}
                    </div>
                    <div className="card-details">
                      <span className="card-duration">{fmtDuration(s.estimated_duration_s)}</span>
                      <span className="card-details-sep" aria-hidden="true">·</span>
                      <span>{fmtTime(s.published_at)}</span>
                    </div>
                  </div>
                  <h2 className="card-title">{s.title}</h2>
                  <div className="card-sub">
                    <span className="card-source">{s.source_domain || s.source}</span>
                    <div className="card-actions">
                      {(s.sources?.length ?? 0) > 1 && (
                        <span
                          className="sources-chip"
                          title={s.sources!.map((r) => r.domain || r.name).join(" · ")}
                        >
                          {s.sources!.length} sources
                        </span>
                      )}
                      <a
                        href={s.source_url || s.source_permalink || s.hn_permalink || "#"}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                      >article ↗</a>
                      <a href="#" onClick={(e) => toggleOpen(s.id, e)}>
                        {openId === s.id ? "hide" : "read"}
                      </a>
                    </div>
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
                </motion.article>
              ))}
            </div>
          </section>
        ))}
      </div>
      )}

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
            >
              {playing ? "❚❚" : "▶"}
            </button>

            <div className="player-cover" aria-hidden="true">
              {current.image_url ? (
                <img src={current.image_url} alt="" loading="lazy" />
              ) : (
                <AbstractCover
                  storyId={current.id}
                  category={current.category}
                  sourceDomain={current.source_domain || current.source}
                  variant="player"
                />
              )}
            </div>

            <div className="player-body">
              <div className="player-title">{current.title}</div>
              <div className="player-meta">
                <span>{current.source_domain || current.source}</span>
                <span aria-hidden="true">·</span>
                <span>{mainCategoryOf(current)}{subCategoryOf(current) ? ` › ${subCategoryOf(current)}` : ""}</span>
                <span aria-hidden="true">·</span>
                <a
                  href={current.source_url || current.source_permalink || current.hn_permalink || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="player-article-link"
                >
                  read the source article ↗
                </a>
              </div>
              <Scrubber now={now} dur={dur || (current.estimated_duration_s ?? 0)} onSeek={seek} />
            </div>

            <div className="player-time">
              <span className="player-time-cur">{fmtDuration(now)}</span>
              <span className="player-time-sep">/</span>
              <span className="player-time-total">
                {fmtDuration(dur || (current.estimated_duration_s ?? 0))}
              </span>
            </div>

            <button
              className="player-close"
              onClick={closePlayer}
              aria-label="Close player"
              title="Close (Esc)"
            >
              ✕
            </button>
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
