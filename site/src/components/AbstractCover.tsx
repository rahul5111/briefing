/**
 * Deterministic abstract cover for stories missing og:image.
 *
 * Bauhaus-inspired: paper background, one bold geometric shape, one strong
 * typographic anchor, one subtle texture. The composition varies per story
 * (hash of id) but always feels like the same publication.
 *
 * Single accent (vermilion) — never breaks the color-consistency lock.
 */
import React from "react";


function hash(str: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

type ShapeKind = "disc" | "arc" | "wedge" | "band" | "chevron" | "grid";
const SHAPES: ShapeKind[] = ["disc", "arc", "wedge", "band", "chevron", "grid"];

type Position = "TL" | "TR" | "BL" | "BR" | "C";
const POSITIONS: Position[] = ["TL", "TR", "BL", "BR", "C"];

const PAPER = "#f1eee6";
const PAPER_2 = "#ebe7dc";
const INK = "#0e1116";
const ACCENT = "#e14522";
const HAIRLINE = "#d9d3c7";

function coords(pos: Position, size: number): { cx: number; cy: number } {
  const s = size;
  const map: Record<Position, { cx: number; cy: number }> = {
    TL: { cx: s * 0.28, cy: s * 0.32 },
    TR: { cx: s * 0.72, cy: s * 0.32 },
    BL: { cx: s * 0.24, cy: s * 0.62 },
    BR: { cx: s * 0.76, cy: s * 0.62 },
    C:  { cx: s * 0.50, cy: s * 0.42 },
  };
  return map[pos] || map.C;
}

function Shape({ kind, pos, w, h, faded }: {
  kind: ShapeKind; pos: Position; w: number; h: number; faded: boolean;
}) {
  const c = coords(pos, Math.min(w, h));
  const fill = faded ? "rgba(225, 69, 34, 0.55)" : ACCENT;
  switch (kind) {
    case "disc": {
      const r = Math.min(w, h) * 0.22;
      return <circle cx={c.cx * (w / Math.min(w, h))} cy={c.cy} r={r} fill={fill} />;
    }
    case "arc": {
      const r = Math.min(w, h) * 0.30;
      const cx = c.cx * (w / Math.min(w, h));
      // draw a half-disc oriented by position
      const rotate =
        pos === "TL" ? 315 : pos === "TR" ? 45 : pos === "BL" ? 225 : pos === "BR" ? 135 : 0;
      return (
        <g transform={`translate(${cx} ${c.cy}) rotate(${rotate})`}>
          <path
            d={`M ${-r} 0 A ${r} ${r} 0 0 1 ${r} 0 Z`}
            fill={fill}
          />
        </g>
      );
    }
    case "wedge": {
      const s = Math.min(w, h) * 0.5;
      const cx = c.cx * (w / Math.min(w, h));
      const rotate =
        pos === "TL" ? 180 : pos === "TR" ? 270 : pos === "BL" ? 90 : pos === "BR" ? 0 : 45;
      return (
        <g transform={`translate(${cx} ${c.cy}) rotate(${rotate})`}>
          <path d={`M 0 0 L ${s} 0 L 0 ${s} Z`} fill={fill} />
        </g>
      );
    }
    case "band": {
      const bandH = h * 0.18;
      const y = pos === "TL" || pos === "TR" ? h * 0.18
              : pos === "C" ? (h - bandH) / 2
              : h * 0.60;
      return <rect x={0} y={y} width={w} height={bandH} fill={fill} />;
    }
    case "chevron": {
      const cx = c.cx * (w / Math.min(w, h));
      const s = Math.min(w, h) * 0.28;
      return (
        <polygon
          points={`${cx - s},${c.cy} ${cx},${c.cy - s * 0.7} ${cx + s},${c.cy} ${cx},${c.cy + s * 0.7}`}
          fill={fill}
        />
      );
    }
    case "grid": {
      const cell = 14;
      const gy = pos === "TL" || pos === "TR" ? 20 : h * 0.42;
      const gx = pos === "TL" || pos === "BL" ? 20 : w - 100;
      return (
        <g>
          {[0, 1, 2, 3].map((r) =>
            [0, 1, 2, 3, 4].map((cIdx) => (
              <rect
                key={`${r}-${cIdx}`}
                x={gx + cIdx * cell}
                y={gy + r * cell}
                width={cell - 3}
                height={cell - 3}
                fill={fill}
                opacity={(r + cIdx) % 3 === 0 ? 1 : 0.35}
              />
            ))
          )}
        </g>
      );
    }
  }
}

type Props = {
  storyId: string;
  category: string;
  sourceDomain?: string;
  variant?: "card" | "featured" | "player";
};

export default function AbstractCover({
  storyId, category, sourceDomain = "", variant = "card",
}: Props) {
  const h = hash(storyId);
  const shape = SHAPES[h % SHAPES.length];
  const pos = POSITIONS[(h >> 3) % POSITIONS.length];
  const faded = ((h >> 6) & 1) === 1;
  const invertBg = ((h >> 7) & 1) === 1;   // rare: use ink bg with paper type

  // Cover box aspect
  const boxW = 400;
  const boxH = variant === "featured" ? 250 : 300;

  const bgColor = invertBg ? INK : PAPER_2;
  const typeColor = invertBg ? PAPER : INK;
  const mutedColor = invertBg ? "rgba(241,238,230,0.55)" : "rgba(14,17,22,0.5)";

  const catText = (category || "News").toUpperCase();
  const catSize = variant === "featured" ? 68 : 52;
  const catY = variant === "featured" ? boxH - 32 : boxH - 26;

  const domainSize = 11;
  const domainY = variant === "featured" ? boxH - 12 : boxH - 10;

  return (
    <svg
      viewBox={`0 0 ${boxW} ${boxH}`}
      preserveAspectRatio="xMidYMid slice"
      width="100%"
      height="100%"
      role="img"
      aria-label={`${catText} story cover`}
      style={{ display: "block" }}
    >
      <rect width={boxW} height={boxH} fill={bgColor} />

      {/* Subtle hairline frame — mimics a bordered print composition */}
      <rect
        x={10} y={10} width={boxW - 20} height={boxH - 20}
        fill="none" stroke={invertBg ? "rgba(255,255,255,0.08)" : HAIRLINE} strokeWidth={1}
      />

      {/* Subtle diagonal texture */}
      <defs>
        <pattern id={`tex-${h}`} patternUnits="userSpaceOnUse" width="12" height="12" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="12"
                stroke={invertBg ? "rgba(255,255,255,0.04)" : "rgba(14,17,22,0.04)"}
                strokeWidth="1" />
        </pattern>
      </defs>
      <rect width={boxW} height={boxH} fill={`url(#tex-${h})`} />

      {/* Bold accent shape */}
      <Shape kind={shape} pos={pos} w={boxW} h={boxH} faded={faded && !invertBg} />

      {/* Category anchor — bottom-left like a book series label */}
      <text
        x={22}
        y={catY}
        fontFamily="Bricolage Grotesque, Inter Tight, sans-serif"
        fontWeight={800}
        fontSize={catSize}
        letterSpacing={-1.2}
        fill={typeColor}
      >
        {catText}
      </text>

      {/* Source domain — small, right-aligned like a colophon */}
      {sourceDomain && (
        <text
          x={boxW - 22}
          y={domainY}
          textAnchor="end"
          fontFamily="JetBrains Mono, monospace"
          fontSize={domainSize}
          letterSpacing={1.4}
          fill={mutedColor}
        >
          {sourceDomain.toUpperCase()}
        </text>
      )}
    </svg>
  );
}
