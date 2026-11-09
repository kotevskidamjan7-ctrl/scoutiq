// Player profile: who he is, what he costs, his 2024/25 score and why, and how 2025/26 went.
import { ReactNode, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, Profile as P } from "../lib/api";
import { useCompare } from "../lib/compare";
import { eur, num, RELIABILITY_TEXT, ROLE_NAMES, signed } from "../lib/format";
import PercentileBars from "../components/PercentileBars";
import ValueChart from "../components/ValueChart";
import SimilarPlayers from "../components/SimilarPlayers";
import { valueTrend } from "../lib/valueTrend";
import PageHeader from "../components/PageHeader";
import BackButton from "../components/BackButton";
import PositionPitch from "../components/PositionPitch";

function Section({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="sheet">
      <h2 className="condensed text-2xl font-bold">{title}</h2>
      {note && <p className="mt-1 text-sm text-ink-soft">{note}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function trendNote(points: { date: string; value_eur: number }[]): string | undefined {
  const t = valueTrend(points);
  if (!t) return undefined;
  const parts: string[] = [];
  if (t.changePct != null) {
    parts.push(t.changePct === 0 ? "Unchanged over the last year"
      : `${t.changePct > 0 ? "Up" : "Down"} ${Math.abs(t.changePct)}% over the last year (${eur(t.yearAgo!.value_eur)} to ${eur(t.latest.value_eur)})`);
  }
  parts.push(t.belowPeakPct <= 0 ? "now at his highest value" : `peak ${eur(t.peak.value_eur)} in ${t.peak.date.slice(0, 4)}, ${t.belowPeakPct}% higher than now`);
  const text = parts.join("; ");
  return text[0].toUpperCase() + text.slice(1) + ". Transfermarkt estimates, not transfer fees.";
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

  if (error) return <div><p role="alert" className="text-signal">{error}</p><BackButton fallback="/players" fallbackName="players" className="mt-3" /></div>;
  if (!p) return <p className="text-ink-soft">Loading…</p>;

  const s = p.scores[0];
  const rf = p.recent_form;
  const stats = p.season_stats.filter((x) => x.season === 2024);
  const picked = compare.has(p.id);

  return (
    <div className="space-y-6">
      <BackButton fallback="/players" fallbackName="players" />
      <PageHeader
        title={p.name}
        subtitle={<>{[s ? ROLE_NAMES[s.role] : p.primary_position, p.age != null && `${p.age} years old`, p.nationality].filter(Boolean).join(", ")}
          {stats[0] && <>. {stats[0].club as string} ({stats[0].league as string}), 2024/25</>}</>}
        actions={s && (
          <button type="button" className={picked ? "btn-quiet" : "btn-primary"}
                  disabled={!picked && compare.full}
                  onClick={() => compare.toggle({ id: p.id, name: p.name, role: s.role })}>
            {picked ? "Remove from comparison" : compare.full ? "Comparison is full (4)" : "Add to comparison"}
          </button>
        )}>
        <dl className="mt-7 grid grid-cols-2 gap-y-5 border-t border-chalk/15 pt-5 lg:grid-cols-4">
          {[
            ["Score 2024/25", s ? s.score.toFixed(1) : "–", s ? `within ${s.league}, 0–100` : "not scored"],
            ["Market value", eur(p.market_value?.value_eur), p.market_value ? `Transfermarkt, ${p.market_value.valuation_date}` : "no valuation"],
            ["Value for money", s ? signed(s.value_for_money) : "–",
              s?.value_for_money != null ? "points vs. what his price predicts" : s?.value_for_money_note ? "not shown for this position" : "no valuation"],
            ["Minutes 2025/26", rf.totals ? num(rf.totals.minutes) : "0", "league minutes, Transfermarkt"],
          ].map(([label, value, note], i) => (
            <div key={label} className={`pr-4 ${i % 2 === 1 ? "pl-4 sm:pl-6" : ""} ${i > 0 ? "lg:border-l lg:border-chalk/15 lg:pl-6" : ""}`}>
              <dt className="text-sm text-chalk-dim">{label}</dt>
              <dd className="condensed num text-5xl font-extrabold leading-tight text-chalk">{value}</dd>
              <dd className="text-xs text-chalk-dim">{note}</dd>
            </div>
          ))}
        </dl>
      </PageHeader>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <aside className="space-y-4 xl:sticky xl:top-6 xl:col-start-2 xl:row-start-1" aria-label="Position and facts">
          <div className="sheet">
            <h2 className="condensed text-2xl font-bold">Where he plays</h2>
            <div className="mx-auto mt-3 max-w-[260px]">
              <PositionPitch title={`${p.name}: ${p.primary_position ?? "position unknown"}`}
                             markers={[
                               ...(p.secondary_position ? [{ key: "second", position: p.secondary_position, role: null, label: "2", color: "#3A5059" }] : []),
                               { key: p.id, position: p.primary_position, role: s?.role ?? null, label: s ? String(Math.round(s.score)) : "–" },
                             ]} />
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              {[
                ["Position", p.primary_position], ["Also plays", p.secondary_position],
                ["Foot", p.foot], ["Height", p.height_cm ? `${p.height_cm} cm` : null],
                ["Nationality", p.nationality], ["Born", p.birth_date],
                ["Adjusted score", s?.score_adjusted != null ? s.score_adjusted.toFixed(1) : null],
                ["Reliability", s?.reliability],
              ].filter(([, v]) => v).map(([k, v]) => (
                <div key={k as string}><dt className="text-ink-faint">{k}</dt><dd className="font-medium">{v}</dd></div>
              ))}
            </dl>
            {p.secondary_position && <p className="mt-3 text-xs text-ink-faint">Yellow: main position with his score. Grey “2”: second position.</p>}
          </div>
        </aside>

        <div className="min-w-0 space-y-6 xl:col-start-1 xl:row-start-1">
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

          {s && (
            <Section title="Similar players"
                     note={`${ROLE_NAMES[s.role]}s whose 2024/25 statistics look most like his. Useful for finding a cheaper or younger alternative.`}>
              <SimilarPlayers playerId={p.id} />
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
            <Section title="Market value" note={trendNote(p.value_history)}>
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
      </div>
    </div>
  );
}
