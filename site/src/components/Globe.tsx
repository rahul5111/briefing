import { useEffect, useMemo, useRef, useState } from "react";
import GlobeGL from "react-globe.gl";

type Story = {
  id: string;
  title: string;
  category: string;
  source_domain: string;
  published_at: string;
  audio_path: string;
  estimated_duration_s: number;
  source_url: string | null;
  hn_permalink: string;
  location?: { name: string; country: string; lat: number; lng: number } | null;
};

type Pin = {
  lat: number;
  lng: number;
  size: number;
  story: Story;
};

type Props = {
  stories: Story[];
  onSelect: (s: Story) => void;
  playingId?: string | null;
};

export default function Globe({ stories, onSelect, playingId }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const globeRef = useRef<any>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [hoverId, setHoverId] = useState<string | null>(null);

  const pins: Pin[] = useMemo(
    () =>
      stories
        .filter((s): s is Story & { location: NonNullable<Story["location"]> } => !!s.location)
        .map((s) => ({
          lat: s.location.lat,
          lng: s.location.lng,
          size: playingId === s.id ? 0.9 : 0.35,
          story: s,
        })),
    [stories, playingId]
  );

  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    const update = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const g = globeRef.current;
    if (!g) return;
    // Slow ambient rotation
    const controls = g.controls?.();
    if (controls) {
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.35;
      controls.enableZoom = true;
      controls.enablePan = false;
    }
    // Frame the globe nicely
    g.pointOfView?.({ altitude: 2.1 }, 0);
  }, []);

  return (
    <div className="globe-wrap" ref={containerRef}>
      <GlobeGL
        ref={globeRef}
        width={size.w}
        height={size.h}
        backgroundColor="rgba(0,0,0,0)"
        showGlobe={true}
        showAtmosphere={true}
        atmosphereColor="#e14522"
        atmosphereAltitude={0.14}
        globeImageUrl="//unpkg.com/three-globe/example/img/earth-blue-marble.jpg"
        bumpImageUrl="//unpkg.com/three-globe/example/img/earth-topology.png"

        pointsData={pins}
        pointLat={(d: any) => d.lat}
        pointLng={(d: any) => d.lng}
        pointColor={(d: any) => (playingId === d.story.id ? "#ff8a6b" : "#e14522")}
        pointAltitude={(d: any) => 0.02 + d.size * 0.06}
        pointRadius={(d: any) => 0.35 + d.size * 0.6}
        pointLabel={(d: any) =>
          `<div style="background:#f1eee6;color:#0e1116;padding:10px 12px;border:1px solid #0e1116;font-family:'Inter Tight',sans-serif;max-width:280px;font-size:14px;line-height:1.3;box-shadow:0 8px 24px rgba(14,17,22,0.18)">
             <div style="color:#e14522;font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:0.12em;margin-bottom:4px;text-transform:uppercase">${d.story.location.name} · ${d.story.category}</div>
             <div style="font-weight:500">${d.story.title}</div>
           </div>`
        }
        onPointClick={(d: any) => onSelect(d.story)}
        onPointHover={(d: any) => setHoverId(d ? d.story.id : null)}
      />
      <div className="globe-legend">
        <div className="globe-legend-count">
          <strong>{pins.length}</strong> STORIES ON THE MAP
        </div>
        <div className="globe-legend-tip">
          click a pin to play · scroll to zoom · drag to rotate
        </div>
      </div>
    </div>
  );
}
