// Side-by-side comparison of 2 to 4 players. Metric bars only when they share a role,
// because percentiles are measured against each role's own regulars.
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, Comparison } from "../lib/api";
import { useCompare } from "../lib/compare";
import { eur, metricValue, num, ROLE_NAMES, signed } from "../lib/format";

// Validated categorical order (adjacent CVD and normal-vision checks pass on white); text never uses these.
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6"];

export default function Compare() {
  const [sp] = useSearchParams();
  const compare = useCompare();
  const ids = sp.getAll("ids").length ? sp.getAll("ids").map(Number) : compare.picks.map((p) => p.id);
  const key = ids.join(",");
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null); setError(null);
    if (ids.length < 2) return;
    api.compare(ids).then(setData).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load the comparison."));
  }, [key]);

  if (ids.length < 2) return (
    <div className="max-w-2xl">
      <h1 className="condensed text-4xl font-bold">Compare players</h1>
      <div className="mt-6 rounded-lg border border-dashed border-rule p-6">
        <p className="font-semibold">{ids.length === 1 ? "Pick one more player." : "No players picked yet."}</p>
        <p className="mt-1 text-ink-soft">Tick “Compare” next to 2 to 4 players in the player list, or use “Add to comparison” on a profile.</p>
        <Link to="/players" className="btn-primary mt-4">Open the player list</Link>
      </div>
    </div>
  );
  if (error) return <p role="alert" className="text-signal">{error}</p>;
  if (!data) return <p className="text-ink-soft">Loading…</p>;

  const ps = data.players;
  const s = ps.map((p) => p.scores[0] ?? null);
  const rows: [string, (i: number) => string][] = [
    ["Role", (i) => (s[i] ? ROLE_NAMES[s[i]!.role] : "–")],
    ["Club 2024/25", (i) => ps[i].season_stats.find((x) => x.season === 2024)?.club as string ?? "–"],
    ["League", (i) => s[i]?.league ?? "–"],
    ["Age", (i) => (ps[i].age != null ? String(ps[i].age) : "–")],
    ["Score 2024/25", (i) => s[i]?.score.toFixed(1) ?? "–"],
    ["Market value", (i) => eur(ps[i].market_value?.value_eur)],
    ["Value for money", (i) => signed(s[i]?.value_for_money)],
    ["Reliability", (i) => s[i]?.reliability ?? "–"],
    ["Minutes 2024/25", (i) => num(s[i]?.minutes)],
    ["Minutes 2025/26", (i) => num(ps[i].recent_form.totals?.minutes ?? 0)],
    ["Goals + assists 2025/26", (i) => { const t = ps[i].recent_form.totals; return t ? `${t.goals} + ${t.assists}` : "–"; }],
  ];
  const metricKeys = data.same_role && s[0] ? s[0].metrics.map((m) => m.key) : [];

  return (
    <div className="max-w-6xl space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="condensed text-4xl font-bold">Compare players</h1>
        {!sp.getAll("ids").length && <button type="button" className="btn-quiet text-sm" onClick={compare.clear}>Clear comparison</button>}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule text-left">
              <th scope="col" className="w-48 py-2 pr-3 font-medium text-ink-soft"><span className="sr-only">Statistic</span></th>
              {ps.map((p, i) => (
                <th key={p.id} scope="col" className="py-2 pr-3 align-bottom">
                  <span className="mb-1 block h-1.5 w-8 rounded-full" style={{ background: SERIES[i] }} aria-hidden="true" />
                  <Link to={`/players/${p.id}`} className="condensed text-xl font-bold underline-offset-4 hover:underline">{p.name}</Link>
                  {!sp.getAll("ids").length && (
                    <button type="button" className="block text-xs font-normal text-ink-faint underline-offset-2 hover:underline"
                            onClick={() => compare.toggle({ id: p.id, name: p.name, role: s[i]?.role ?? "" })}>Remove</button>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, f]) => (
              <tr key={label} className="border-b border-rule/70">
                <th scope="row" className="py-2 pr-3 text-left font-normal text-ink-soft">{label}</th>
                {ps.map((p, i) => <td key={p.id} className="num py-2 pr-3">{f(i)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.same_role ? (
        <section aria-labelledby="metrics-title">
          <h2 id="metrics-title" className="condensed text-2xl font-bold">Score breakdown</h2>
          <p className="mt-1 text-sm text-ink-soft">
            Percentile against regular {ROLE_NAMES[s[0]!.role].toLowerCase()}s in each player's own league, 2024/25. Raw values in brackets.
          </p>
          <ul className="mt-3 flex flex-wrap gap-4 text-sm" aria-label="Legend">
            {ps.map((p, i) => (
              <li key={p.id} className="flex items-center gap-2">
                <span className="h-3 w-3 rounded-sm" style={{ background: SERIES[i] }} aria-hidden="true" />{p.name}
              </li>
            ))}
          </ul>
          <div className="mt-5 grid gap-x-10 gap-y-6 md:grid-cols-2">
            {metricKeys.map((k) => {
              const ms = s.map((x) => x?.metrics.find((m) => m.key === k) ?? null);
              const label = ms.find(Boolean)?.label ?? k;
              return (
                <div key={k}>
                  <h3 className="text-sm font-semibold">{label}{ms.find(Boolean)?.lower_is_better && <span className="font-normal text-ink-faint">, lower is better</span>}</h3>
                  <ul className="mt-2 space-y-[2px]">
                    {ps.map((p, i) => {
                      const m = ms[i];
                      const pct = m?.percentile ?? null;
                      return (
                        <li key={p.id} className="flex items-center gap-2" title={`${p.name}: ${pct == null ? "not recorded" : `percentile ${Math.round(pct)}`}`}>
                          <span className="sr-only">{p.name}</span>
                          <div className="relative h-4 flex-1" role="img" aria-label={`${p.name}: ${pct == null ? "not recorded" : `percentile ${Math.round(pct)}`}`}>
                            {pct != null && <div className="absolute inset-y-0 left-0 rounded-r" style={{ width: `${Math.max(pct, 1)}%`, background: SERIES[i] }} />}
                          </div>
                          <span className="num w-24 text-right text-xs">
                            <span className="font-semibold">{pct == null ? "–" : Math.round(pct)}</span>
                            <span className="text-ink-faint"> ({m ? metricValue(m.kind, m.value) : "–"})</span>
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })}
          </div>
        </section>
      ) : (
        <p className="rounded-md bg-surface-sunk p-4 text-sm">
          These players have different roles, so their score breakdowns use different statistics and are not shown side by side.
          Each score still says how a player ranks among regulars in his own role and league.
        </p>
      )}
    </div>
  );
}
