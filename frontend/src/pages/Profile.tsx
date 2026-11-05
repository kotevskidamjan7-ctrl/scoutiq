// Player profile: who he is, what he costs, his 2024/25 score and why, and how 2025/26 went.
import { ReactNode, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, Profile as P } from "../lib/api";
import { useCompare } from "../lib/compare";
import { eur, num, RELIABILITY_TEXT, ROLE_NAMES, signed } from "../lib/format";
import PercentileBars from "../components/PercentileBars";
import ValueChart from "../components/ValueChart";

function Section({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-rule bg-surface-raised p-5">
      <h2 className="condensed text-2xl font-bold">{title}</h2>
      {note && <p className="mt-1 text-sm text-ink-soft">{note}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

const STAT_ROWS: [string, string][] = [
  ["appearances", "Appearances"], ["lineups", "Starts"], ["minutes", "Minutes"], ["goals", "Goals"],
  ["assists", "Assists"], ["shots_total", "Shots"], ["shots_on", "Shots on target"], ["passes_total", "Passes"],
  ["passes_key", "Key passes"], ["tackles", "Tackles"], ["interceptions", "Interceptions"], ["blocks", "Blocks"],
  ["duels_won", "Duels won"], ["duels_total", "Duels"], ["dribbles_success", "Successful dribbles"],
  ["fouls_drawn", "Fouls drawn"], ["fouls_committed", "Fouls committed"], ["cards_yellow", "Yellow cards"],
  ["cards_red", "Red cards"], ["saves", "Saves"], ["goals_conceded", "Goals conceded"],
];

export default function Profile() {
  const { id } = useParams();
  const [p, setP] = useState<P | null>(null);
  const [error, setError] = useState<string | null>(null);
  const compare = useCompare();

  useEffect(() => {
    setP(null); setError(null);
    api.player(Number(id)).then(setP).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load the player."));
  }, [id]);

  if (error) return <div><p role="alert" className="text-signal">{error}</p><Link to="/players" className="mt-3 inline-block underline">Back to players</Link></div>;
  if (!p) return <p className="text-ink-soft">Loading…</p>;

  const s = p.scores[0];
  const rf = p.recent_form;
  const stats = p.season_stats.filter((x) => x.season === 2024);
  const picked = compare.has(p.id);

  return (
    <div className="max-w-5xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to="/players" className="text-sm text-ink-soft underline-offset-4 hover:underline">Players</Link>
          <h1 className="condensed text-5xl font-extrabold leading-none">{p.name}</h1>
          <p className="mt-2 text-ink-soft">
            {[s ? ROLE_NAMES[s.role] : p.primary_position, p.age != null && `${p.age} years old`, p.nationality,
              p.foot && `${p.foot} foot`, p.height_cm && `${p.height_cm} cm`].filter(Boolean).join(", ")}
          </p>
          {stats[0] && <p className="text-ink-soft">{stats[0].club} ({stats[0].league}) in 2024/25</p>}
        </div>
        {s && (
          <button type="button" className={picked ? "btn-quiet" : "btn-primary"}
                  disabled={!picked && compare.full}
                  onClick={() => compare.toggle({ id: p.id, name: p.name, role: s.role })}>
            {picked ? "Remove from comparison" : compare.full ? "Comparison is full (4)" : "Add to comparison"}
          </button>
        )}
      </header>

      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-rule bg-rule sm:grid-cols-4">
        {[
          ["Scouting score 2024/25", s ? s.score.toFixed(1) : "–", s ? `Within ${s.league}, 0–100` : "Not scored"],
          ["Market value", eur(p.market_value?.value_eur), p.market_value ? `Transfermarkt, ${p.market_value.valuation_date}` : "No valuation"],
          ["Value for money", s ? signed(s.value_for_money) : "–",
            s?.value_for_money != null ? "Points vs. what his price predicts" : s?.value_for_money_note ? "Not shown for this role" : "No valuation"],
          ["Minutes 2025/26", rf.totals ? num(rf.totals.minutes) : "0", "League minutes, Transfermarkt"],
        ].map(([label, value, note]) => (
          <div key={label} className="bg-surface-raised p-4">
            <dt className="text-sm text-ink-soft">{label}</dt>
            <dd className="condensed num text-4xl font-bold">{value}</dd>
            <dd className="text-xs text-ink-faint">{note}</dd>
          </div>
        ))}
      </dl>

      {s && (
        <Section title="Why this score"
                 note={<>Score {s.score.toFixed(1)}: better than {Math.round(s.score)}% of regular {ROLE_NAMES[s.role].toLowerCase()}s
                   in {s.league}, from {num(s.minutes)} league minutes. Reliability: {RELIABILITY_TEXT[s.reliability] ?? s.reliability}.</>}>
          <PercentileBars metrics={s.metrics} />
          {s.dropped_metrics.length > 0 && (
            <p className="mt-3 text-sm text-ink-soft">
              Not used because the data source does not record it in this league: {s.dropped_metrics.join(", ")}.
            </p>
          )}
          {s.position_check?.consistent === false && (
            <p className="mt-2 text-sm text-signal">
              API-Football listed him as “{s.position_check.api_position}” in 2024/25, which does not match this role.
              Read the score with care.
            </p>
          )}
          {s.value_for_money_note && <p className="mt-2 text-sm text-ink-soft">{s.value_for_money_note}</p>}
          {s.score_adjusted != null && (
            <p className="mt-2 text-sm text-ink-soft">League-strength adjusted score: <span className="num font-semibold">{s.score_adjusted.toFixed(1)}</span>.</p>
          )}
        </Section>
      )}

      <Section title="Recent form 2025/26"
               note="Basic league numbers only. The score above is from 2024/25, the last season with full statistics.">
        {rf.rows.length === 0 ? (
          <p className="text-ink-soft">No league minutes recorded in 2025/26 in the supported leagues.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead><tr className="border-b border-rule text-left text-ink-soft">
                <th className="py-2 pr-3 font-medium">Club</th>
                {["Apps", "Minutes", "Goals", "Assists", "Yellow", "Red"].map((h) => <th key={h} className="py-2 pr-3 text-right font-medium">{h}</th>)}
              </tr></thead>
              <tbody>
                {rf.rows.map((r) => (
                  <tr key={r.club + r.league} className="border-b border-rule/70">
                    <td className="py-2 pr-3">{r.club}<span className="block text-xs text-ink-faint">{r.league}</span></td>
                    {[r.appearances, r.minutes, r.goals, r.assists, r.cards_yellow, r.cards_red].map((v, i) =>
                      <td key={i} className="num py-2 pr-3 text-right">{num(v)}</td>)}
                  </tr>
                ))}
                {rf.rows.length > 1 && rf.totals && (
                  <tr className="font-semibold">
                    <td className="py-2 pr-3">Total</td>
                    {[rf.totals.appearances, rf.totals.minutes, rf.totals.goals, rf.totals.assists, rf.totals.cards_yellow, rf.totals.cards_red]
                      .map((v, i) => <td key={i} className="num py-2 pr-3 text-right">{num(v)}</td>)}
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-ink-faint">Source: Transfermarkt match data.</p>
      </Section>

      {p.value_history.length > 0 && (
        <Section title="Market value">
          <ValueChart points={p.value_history} />
        </Section>
      )}

      {stats.length > 0 && (
        <Section title="Season statistics 2024/25" note="League matches only. A dash means the source did not record it.">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-rule text-left text-ink-soft">
                <th className="py-2 pr-3 font-medium">Statistic</th>
                {stats.map((x) => <th key={x.club + x.league} className="py-2 pr-3 text-right font-medium">{x.club}</th>)}
              </tr></thead>
              <tbody>
                {STAT_ROWS.map(([k, label]) => (
                  <tr key={k} className="border-b border-rule/70">
                    <td className="py-1.5 pr-3 text-ink-soft">{label}</td>
                    {stats.map((x) => <td key={x.club + x.league} className="num py-1.5 pr-3 text-right">{num(x[k] as number | null)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-ink-faint">Source: API-Football.</p>
        </Section>
      )}
    </div>
  );
}
