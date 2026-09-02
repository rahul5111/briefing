import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";

type Story = {
  id: string;
  title: string;
  summary: string;
  category: string;
  source_url: string | null;
  source_domain: string;
  hn_permalink: string;
  hn_score: number;
  published_at: string;
  created_at_ts: number;
  audio_path: string;
  word_count: number;
  estimated_duration_s: number;
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
 * Waveform canvas — the one authored moment. Draws either:
 *  - a live-audio spectrum (via WebAudio AnalyserNode) when playing, or
 *  - a subtle idle baseline (a low horizon line) when paused.
 * Falls back to idle if WebAudio setup fails (e.g. CORS on remote audio).
 */
function useWaveform(
  audioEl: HTMLAudioElement | null,
  playing: boolean
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!audioEl || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const cvsCtx = canvas.getContext("2d");
    if (!cvsCtx) return;

    const setSize = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      cvsCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    setSize();
    const ro = new ResizeObserver(setSize);
    ro.observe(canvas);

    const drawIdle = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      cvsCtx.clearRect(0, 0, w, h);
      cvsCtx.strokeStyle = "rgba(123,135,148,0.35)";
      cvsCtx.lineWidth = 1;
      cvsCtx.beginPath();
      cvsCtx.moveTo(0, h / 2);
      cvsCtx.lineTo(w, h / 2);
      cvsCtx.stroke();
    };

    const drawLive = () => {
      if (!analyserRef.current) return;
      const a = analyserRef.current;
      const bins = a.frequencyBinCount;
      const data = new Uint8Array(bins);
      a.getByteFrequencyData(data);

      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      cvsCtx.clearRect(0, 0, w, h);

      const barCount = 64;
      const step = Math.floor(bins / barCount);
      const barW = w / barCount;
      cvsCtx.fillStyle = "#e8a64b";
      for (let i = 0; i < barCount; i++) {
        let sum = 0;
        for (let j = 0; j < step; j++) sum += data[i * step + j];
        const v = sum / step / 255;
        const barH = Math.max(1, v * h * 0.9);
        cvsCtx.fillRect(i * barW + 0.5, (h - barH) / 2, barW - 1.5, barH);
      }
      rafRef.current = requestAnimationFrame(drawLive);
    };

    if (!playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      drawIdle();
      return () => ro.disconnect();
    }

    // Lazy-init WebAudio graph
    try {
      if (!ctxRef.current) {
        const AC = window.AudioContext || (window as any).webkitAudioContext;
        ctxRef.current = new AC();
      }
      const ctx = ctxRef.current!;
      if (ctx.state === "suspended") ctx.resume();

      if (!sourceRef.current) {
        sourceRef.current = ctx.createMediaElementSource(audioEl);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.75;
        sourceRef.current.connect(analyser);
        analyser.connect(ctx.destination);
        analyserRef.current = analyser;
      }
      rafRef.current = requestAnimationFrame(drawLive);
    } catch (e) {
      drawIdle();
    }

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      ro.disconnect();
    };
  }, [audioEl, playing]);

  return canvasRef;
}

export default function Feed({ stories, cdnBase }: Props) {
  const [current, setCurrent] = useState<Story | null>(null);
  const [playing, setPlaying] = useState(false);
  const [now, setNow] = useState(0);
  const [dur, setDur] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const [activeCat, setActiveCat] = useState<string>("ALL");
  const [nowMs, setNowMs] = useState(() =>
    stories.length ? new Date(stories[0].published_at).getTime() : 0
  );
  useEffect(() => { setNowMs(Date.now()); }, []);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useWaveform(audioRef.current, playing);

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

      <div className={`player ${playing ? "playing" : ""}`} role="region" aria-label="Now playing">
        <button
          className="btn"
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
        <div className="now">
          <div className="title">{current ? current.title : "Select a story to play"}</div>
          <canvas ref={canvasRef} aria-hidden="true" />
        </div>
        <div className="time">
          {fmtDuration(now)} / {fmtDuration(dur || (current?.estimated_duration_s ?? 0))}
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
