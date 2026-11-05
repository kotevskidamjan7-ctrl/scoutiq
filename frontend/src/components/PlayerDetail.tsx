import { Link } from "react-router-dom";
import type { PlayerOut } from "../lib/api";
import { eur, ROLE_NAMES } from "../lib/format";

const RELIABILITY: Record<string, string> = {
  high: "High: 1,800+ league minutes",
  medium: "Medium: 900–1,799 league minutes",
  low: "Low: under 900 minutes, or many statistics missing",
};

export default function PlayerDetail({ p, onClose }: { p: PlayerOut; onClose: () => void }) {
  return (
    <section aria-label={`Details for ${p.name}`} className="rounded-lg border border-rule bg-surface-raised p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="condensed text-2xl font-bold leading-tight">{p.name}</h3>
          <p className="text-sm text-ink-soft">
            {ROLE_NAMES[p.role]} at {p.club_2024_25} ({p.league}), 2024/25
          </p>
        </div>
        <button type="button" onClick={onClose} className="btn-quiet px-3 py-1 text-sm">Close</button>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
        <div><dt className="text-ink-faint">Scouting score</dt><dd className="condensed num text-2xl font-bold">{p.score.toFixed(1)}</dd></div>
        <div>
          <dt className="text-ink-faint">Market value</dt>
          <dd className="condensed num text-2xl font-bold">{eur(p.price_eur)}</dd>
          {p.valuation_date && <dd className="text-xs text-ink-faint">Transfermarkt, {p.valuation_date}</dd>}
        </div>
        <div><dt className="text-ink-faint">Age today</dt><dd className="condensed num text-2xl font-bold">{p.age ?? "–"}</dd></div>
        <div>
          <dt className="text-ink-faint">League minutes</dt>
          <dd className="num">{p.minutes_2024_25.toLocaleString("en")} in 2024/25</dd>
          <dd className="num">{p.minutes_2025_26.toLocaleString("en")} in 2025/26</dd>
        </div>
      </dl>
      <p className="mt-4 text-sm text-ink-soft">Reliability: {RELIABILITY[p.reliability] ?? p.reliability}</p>
      <Link to={`/players/${p.player_id}`} className="mt-3 inline-block text-sm font-semibold underline underline-offset-4">
        Open full profile
      </Link>
      {p.position_consistent === false && (
        <p className="mt-1 text-sm text-signal">
          In 2024/25 he was listed in a different position from his current role, so his score compares him with players he may not have played among.
        </p>
      )}
    </section>
  );
}
