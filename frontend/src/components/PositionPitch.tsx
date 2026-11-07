// A small chalk pitch with markers for where players play (one marker per player).
import { PitchLines } from "./TacticsBoard";
import { positionXY } from "../lib/positions";
import type { Role } from "../lib/api";

export interface Marker {
  key: string | number;
  position: string | null;
  role: Role | null;
  label: string;          // shown inside the marker (e.g. the score)
  caption?: string;       // shown under it (e.g. a surname)
  color?: string;         // fill; default the marker yellow
}

/** Dark or white text, whichever has more contrast on the marker colour (WCAG relative luminance). */
function textOn(hex: string): string {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  const L = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  const dark = 0.0225; // luminance of #22343C
  return (L + 0.05) / (dark + 0.05) >= 1.05 / (L + 0.05) ? "#22343C" : "#FFFFFF";
}

export default function PositionPitch({ markers, className = "", title }: { markers: Marker[]; className?: string; title: string }) {
  // players on the same spot are spread sideways so none hides another
  const placed: { m: Marker; x: number; y: number }[] = [];
  for (const m of markers) {
    const xy = positionXY(m.position, m.role);
    if (!xy) continue;
    const same = placed.filter((p) => Math.abs(p.x - xy[0]) < 8 && Math.abs(p.y - xy[1]) < 6).length;
    placed.push({ m, x: Math.min(90, Math.max(10, xy[0] + same * 14 * (same % 2 ? 1 : -1))), y: xy[1] });
  }
  return (
    <figure className={`relative aspect-[2/3] w-full overflow-hidden rounded-lg bg-board ${className}`} aria-label={title}>
      <PitchLines />
      {placed.map(({ m, x, y }) => (
        <div key={m.key} className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center"
             style={{ left: `${x}%`, top: `${y}%` }}>
          <span className="condensed num flex h-11 w-11 items-center justify-center rounded-full text-lg font-bold ring-2 ring-chalk/80"
                style={{ background: m.color ?? "#F2C230", color: textOn(m.color ?? "#F2C230") }}>
            {m.label}
          </span>
          {m.caption && <span className="narrow mt-1 max-w-[7rem] truncate text-xs font-semibold text-chalk">{m.caption}</span>}
        </div>
      ))}
      {placed.length === 0 && (
        <figcaption className="absolute inset-x-6 top-1/2 -translate-y-1/2 text-center text-sm text-chalk-dim">Position unknown</figcaption>
      )}
    </figure>
  );
}
