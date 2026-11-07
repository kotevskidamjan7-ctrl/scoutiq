// Preview of a player beside the player list: where he plays, his score and why, without leaving the list.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Profile } from "../lib/api";
import { useCompare } from "../lib/compare";
import { eur, metricValue, num, ROLE_NAMES, signed } from "../lib/format";
import PositionPitch from "./PositionPitch";

export default function PlayerCard({ id, shownScore, onClose }: { id: number; shownScore: number | null; onClose: () => void }) {
  const [p, setP] = useState<Profile | null>(null);
  const [failed, setFailed] = useState(false);
  const compare = useCompare();
  useEffect(() => {
    let live = true;
    setP(null); setFailed(false);
    api.player(id).then((r) => live && setP(r)).catch(() => live && setFailed(true));
    return () => { live = false; };
  }, [id]);

  if (failed) return <div className="sheet text-sm text-signal">Could not load this player.</div>;
  if (!p) return <div className="sheet text-sm text-ink-soft" aria-busy="true">Loading player…</div>;

  const s = p.scores[0];
  const top = s ? [...s.metrics].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)).slice(0, 5) : [];
  const rf = p.recent_form.totals;
  const club = p.season_stats.find((x) => x.season === 2024);
  const picked = compare.has(p.id);
  const score = shownScore ?? s?.score ?? null;

  return (
    <article className="sheet space-y-4" aria-label={`Preview of ${p.name}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="condensed text-3xl font-extrabold leading-none">{p.name}</h2>
          <p className="mt-1 text-sm text-ink-soft">
            {[p.primary_position ?? (s ? ROLE_NAMES[s.role] : null), p.age != null && `${p.age}`, p.nationality].filter(Boolean).join(", ")}
          </p>
          {club && <p className="text-sm text-ink-soft">{club.club as string} ({club.league as string}), 2024/25</p>}
        </div>
        <button type="button" onClick={onClose} className="btn-quiet px-2.5 py-1 text-sm" aria-label="Close the preview">×</button>
      </div>

      <div className="grid grid-cols-[minmax(0,9rem)_1fr] gap-4">
        <PositionPitch title={`${p.name} plays as ${p.primary_position ?? "unknown position"}`}
                       markers={[{ key: p.id, position: p.primary_position, role: s?.role ?? null, label: score != null ? String(Math.round(score)) : "–" }]} />
        <dl className="grid content-start gap-3 text-sm">
          <div><dt className="text-ink-faint">Score 2024/25</dt><dd className="condensed num text-3xl font-bold">{score != null ? score.toFixed(1) : "–"}</dd></div>
          <div><dt className="text-ink-faint">Market value</dt><dd className="num font-semibold">{eur(p.market_value?.value_eur)}</dd></div>
          <div><dt className="text-ink-faint">Value for money</dt><dd className="num font-semibold">{s ? signed(s.value_for_money) : "–"}</dd></div>
          <div><dt className="text-ink-faint">2025/26</dt>
            <dd className="num font-semibold">{rf ? `${num(rf.minutes)} min, ${rf.goals} G, ${rf.assists} A` : "no league minutes"}</dd></div>
        </dl>
      </div>

      {top.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold">Strongest weights in his score</h3>
          <ul className="mt-2 space-y-1.5">
            {top.map((m) => (
              <li key={m.key} className="grid grid-cols-[minmax(0,1fr)_6rem_2rem] items-center gap-2 text-sm">
                <span className="truncate" title={m.label}>{m.label} <span className="text-ink-faint">{metricValue(m.kind, m.value)}</span></span>
                <span className="relative h-2 rounded-full bg-surface-sunk" role="img" aria-label={`percentile ${Math.round(m.percentile ?? 0)}`}>
                  <span className="absolute inset-y-0 left-0 rounded-full bg-board" style={{ width: `${Math.max(2, m.percentile ?? 0)}%` }} />
                </span>
                <span className="num text-right font-semibold">{Math.round(m.percentile ?? 0)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-ink-faint">Percentile among regulars in his position and league.</p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Link to={`/players/${p.id}`} className="btn-primary py-1.5">Open full profile</Link>
        {s && (
          <button type="button" className="btn-quiet py-1.5" disabled={!picked && compare.full}
                  onClick={() => compare.toggle({ id: p.id, name: p.name, role: s.role })}>
            {picked ? "Remove from comparison" : "Add to comparison"}
          </button>
        )}
      </div>
    </article>
  );
}
