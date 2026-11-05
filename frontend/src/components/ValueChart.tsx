// Transfermarkt market value over time: one line, hover or arrow keys for exact points.
import { KeyboardEvent, PointerEvent, useEffect, useMemo, useRef, useState } from "react";
import { eur } from "../lib/format";

interface Point { date: string; value_eur: number; }

const H = 220, PAD = { l: 52, r: 16, t: 14, b: 26 };

function niceMax(v: number) {
  const p = 10 ** Math.floor(Math.log10(v || 1));
  return Math.ceil(v / p / (v / p > 5 ? 2 : 1)) * p * (v / p > 5 ? 2 : 1);
}

export default function ValueChart({ points }: { points: Point[] }) {
  const ref = useRef<SVGSVGElement>(null);
  const box = useRef<HTMLElement>(null);
  const [active, setActive] = useState<number | null>(null);
  // draw at the real width so text stays at its real size on phones
  const [W, setW] = useState(800);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const data = useMemo(() => points.map((p) => ({ ...p, t: new Date(p.date).getTime() })), [points]);
  if (data.length < 2) return <p className="text-sm text-ink-soft">Not enough valuations to draw a history.</p>;

  const t0 = data[0].t, t1 = data[data.length - 1].t;
  const vmax = niceMax(Math.max(...data.map((d) => d.value_eur)));
  const x = (t: number) => PAD.l + ((t - t0) / (t1 - t0 || 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => H - PAD.b - (v / vmax) * (H - PAD.t - PAD.b);
  const path = data.map((d, i) => `${i ? "L" : "M"}${x(d.t).toFixed(1)},${y(d.value_eur).toFixed(1)}`).join("");
  const ticks = [0, vmax / 2, vmax];
  // label 1 January of each year inside the range (a label at the very start would crowd the next one)
  const years = Array.from(new Set(data.map((d) => new Date(d.t).getFullYear()))).filter((yr) => new Date(yr, 0, 1).getTime() >= t0);
  const step = Math.ceil(years.length / Math.max(2, Math.floor(W / 90)));

  const nearest = (clientX: number) => {
    const rect = ref.current!.getBoundingClientRect();
    const px = ((clientX - rect.left) / rect.width) * W;
    let best = 0;
    data.forEach((d, i) => { if (Math.abs(x(d.t) - px) < Math.abs(x(data[best].t) - px)) best = i; });
    return best;
  };
  const onMove = (e: PointerEvent) => setActive(nearest(e.clientX));
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight") setActive((a) => Math.min((a ?? -1) + 1, data.length - 1));
    if (e.key === "ArrowLeft") setActive((a) => Math.max((a ?? data.length) - 1, 0));
  };
  const a = active != null ? data[active] : null;

  return (
    <figure ref={box} className="relative">
      <svg ref={ref} width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block max-w-full touch-none" role="img" tabIndex={0}
           aria-label={`Market value from ${eur(data[0].value_eur)} on ${data[0].date} to ${eur(data[data.length - 1].value_eur)} on ${data[data.length - 1].date}. Use the arrow keys to read each valuation.`}
           onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setActive(null)} onKeyDown={onKey} onBlur={() => setActive(null)}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="#D3DBD8" strokeWidth={1} />
            <text x={PAD.l - 8} y={y(v) + 4} textAnchor="end" className="fill-ink-faint text-[11px]">{eur(v)}</text>
          </g>
        ))}
        {years.filter((_, i) => i % step === 0).map((yr) => {
          const t = new Date(yr, 0, 1).getTime();
          return <text key={yr} x={x(t)} y={H - 6} textAnchor="middle" className="fill-ink-faint text-[11px]">{yr}</text>;
        })}
        <path d={path} fill="none" stroke="#22343C" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={x(data[data.length - 1].t)} cy={y(data[data.length - 1].value_eur)} r={4} fill="#22343C" stroke="#fff" strokeWidth={2} />
        {a && (
          <g>
            <line x1={x(a.t)} x2={x(a.t)} y1={PAD.t} y2={H - PAD.b} stroke="#7D8C90" strokeWidth={1} />
            <circle cx={x(a.t)} cy={y(a.value_eur)} r={5} fill="#22343C" stroke="#fff" strokeWidth={2} />
          </g>
        )}
      </svg>
      {a && (
        <div className="pointer-events-none absolute top-0 rounded-md border border-rule bg-surface-raised px-2 py-1 text-xs shadow-sm"
             style={{ left: `${(x(a.t) / W) * 100}%`, transform: `translateX(${x(a.t) > W / 2 ? "-105%" : "5%"})` }}>
          <span className="num block font-semibold">{eur(a.value_eur)}</span>
          <span className="text-ink-faint">{new Date(a.t).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span>
        </div>
      )}
      <figcaption className="mt-1 text-xs text-ink-faint">Transfermarkt market value estimates. Not transfer fees.</figcaption>
    </figure>
  );
}
