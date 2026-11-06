// Dashboard: what the data covers, how fresh it is, and where the value is right now.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, Dashboard as D, DashboardLeague, PlayerRow, Role } from "../lib/api";
import { eur, num, ROLE_NAMES, signed } from "../lib/format";

const ROLES: Role[] = ["GK", "CB", "FB", "CM", "AW", "ST"];
const CAPS = [1_000_000, 3_000_000, 10_000_000];
const CAP_KEY = "scoutiq.dashboardCap";
const THRESHOLD = 0.9; // a league's scores are final once 90% of its regulars have full statistics

const STATUS: Record<DashboardLeague["status"], { label: string; note: string; mark: string }> = {
  complete: { label: "Complete", note: "Scores are final", mark: "bg-board" },
  provisional: { label: "Incomplete", note: "Fetch not finished, scores will change", mark: "bg-marker" },
  no_data: { label: "No data yet", note: "Not fetched", mark: "bg-rule" },
};

const dateText = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "–";
const timeText = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";

function CoverageBar({ value }: { value: number }) {
  const pct = Math.round(value * 1000) / 10;
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-2.5 w-32 rounded-full bg-surface-sunk" role="img"
           aria-label={`${pct}% of regulars have full statistics`}>
        <div className="absolute inset-y-0 left-0 rounded-full bg-board" style={{ width: `${Math.min(100, pct)}%` }} />
        <div className="absolute -inset-y-1 w-px bg-ink-faint" style={{ left: `${THRESHOLD * 100}%` }} aria-hidden="true" />
      </div>
      <span className="num w-12 text-right">{pct.toFixed(1)}%</span>
    </div>
  );
}

function PickList({ picks, metric }: { picks: PlayerRow[]; metric: "vfm" | "score" }) {
  return (
    <ol className="mt-1">
      {picks.map((p) => (
        <li key={p.player_id} className="flex items-baseline justify-between gap-3 border-b border-rule/60 py-2">
          <span className="min-w-0">
            <Link to={`/players/${p.player_id}`} className="font-semibold underline-offset-4 hover:underline">{p.name}</Link>
            <span className="block text-xs text-ink-faint">{p.club}, {p.league}</span>
            <span className="block text-xs text-ink-faint">
              Age {p.age ?? "–"}, {eur(p.price_eur)}{metric === "vfm" && `, score ${p.score.toFixed(1)}`}
            </span>
          </span>
          <span className="num shrink-0 text-right">
            <span className="font-semibold">{metric === "vfm" ? signed(p.value_for_money) : p.score.toFixed(1)}</span>
            <span className="block text-xs text-ink-faint">{metric === "vfm" ? "vs. price" : "score"}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

export default function Dashboard() {
  const [d, setD] = useState<D | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cap, setCapState] = useState<number>(() => {
    try { const v = Number(localStorage.getItem(CAP_KEY)); return CAPS.includes(v) ? v : 3_000_000; } catch { return 3_000_000; }
  });
  const setCap = (v: number) => { setCapState(v); try { localStorage.setItem(CAP_KEY, String(v)); } catch { /* not stored */ } };

  useEffect(() => {
    api.dashboard().then(setD).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load the dashboard."));
  }, []);

  if (error) return <p role="alert" className="rounded-md bg-signal-soft px-3 py-2 text-signal">{error}</p>;
  if (!d) return <p className="text-ink-soft">Loading…</p>;

  const t = d.totals;
  const partial = d.leagues.filter((l) => l.status === "provisional").map((l) => l.name);
  const empty = d.leagues.filter((l) => l.status === "no_data").map((l) => l.name);
  const list = (names: string[]) => names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0];
  const adj = d.model.league_adjustment;

  return (
    <div className="max-w-6xl space-y-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="condensed text-4xl font-bold leading-tight">Dashboard</h1>
          <p className="mt-1 text-ink-soft">
            Scores from the 2024/25 season, recent form from 2025/26. Market values from Transfermarkt, latest {dateText(t.latest_valuation_date)}.
          </p>
        </div>
        <Link to="/builder" className="btn-primary">Build a squad</Link>
      </div>

      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-rule bg-rule lg:grid-cols-4">
        {[
          ["Players scored", num(t.players_scored), "With a 2024/25 score"],
          ["Regulars", num(t.regulars_scored), "900+ league minutes in 2024/25"],
          ["Still playing", num(t.still_playing), "900+ league minutes in 2025/26"],
          ["Leagues complete", `${t.leagues_complete} of ${t.leagues_enabled}`, "Statistics for 90%+ of regulars"],
        ].map(([label, value, note]) => (
          <div key={label} className="bg-surface-raised p-4">
            <dt className="text-sm text-ink-soft">{label}</dt>
            <dd className="condensed num text-4xl font-bold">{value}</dd>
            <dd className="text-xs text-ink-faint">{note}</dd>
          </div>
        ))}
      </dl>

      <section aria-labelledby="leagues-title">
        <h2 id="leagues-title" className="condensed text-2xl font-bold">Leagues</h2>
        {partial.length > 0 && (
          <p className="mt-1 text-sm text-ink-soft">
            {list(partial)} {partial.length === 1 ? "is" : "are"} only partly fetched. Players there are ranked against
            part of the league, so their scores will change once the fetch finishes.
          </p>
        )}
        {empty.length > 0 && (
          <p className="mt-1 text-sm text-ink-soft">{list(empty)} {empty.length === 1 ? "has" : "have"} no statistics yet.</p>
        )}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[860px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-rule text-left text-ink-soft">
                <th scope="col" className="py-2 pr-3 font-medium">League</th>
                <th scope="col" className="py-2 pr-3 font-medium">Status</th>
                <th scope="col" className="py-2 pr-3 font-medium">Regulars with full statistics</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Scored</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Regulars</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Median value</th>
                <th scope="col" className="py-2 font-medium">Regulars by role</th>
              </tr>
            </thead>
            <tbody>
              {d.leagues.map((l) => {
                const s = STATUS[l.status];
                return (
                  <tr key={l.id} className="border-b border-rule/70">
                    <td className="py-2.5 pr-3">
                      <Link to={`/players?league=${l.id}`} className="font-semibold underline-offset-4 hover:underline">{l.name}</Link>
                      <span className="block text-xs text-ink-faint">{l.country}</span>
                    </td>
                    <td className="py-2.5 pr-3">
                      <span className="flex items-center gap-2 font-medium">
                        <span className={`h-2.5 w-2.5 rounded-full ${s.mark}`} aria-hidden="true" />{s.label}
                      </span>
                      <span className="block text-xs text-ink-faint">{s.note}</span>
                    </td>
                    <td className="py-2.5 pr-3">{l.status === "no_data" ? <span className="text-ink-faint">–</span> : <CoverageBar value={l.coverage} />}</td>
                    <td className="num py-2.5 pr-3 text-right">{num(l.scored)}</td>
                    <td className="num py-2.5 pr-3 text-right">{num(l.regulars)}</td>
                    <td className="num py-2.5 pr-3 text-right">{eur(l.median_value_eur)}</td>
                    <td className="num py-2.5 text-xs text-ink-soft">
                      {ROLES.filter((r) => l.roles[r]).map((r) => `${r} ${l.roles[r]}`).join(", ") || "–"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-ink-faint">
          Regulars with full statistics: the share of Transfermarkt regulars (900+ minutes) that also have API-Football statistics.
          The thin line marks 90%, where a league counts as complete.
        </p>
      </section>

      <section aria-labelledby="value-title">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="value-title" className="condensed text-2xl font-bold">Best value right now</h2>
            <p className="mt-1 max-w-3xl text-sm text-ink-soft">
              Reliable scores from complete leagues, players who still played 900+ minutes in 2025/26.
              Where price predicts a role's score well enough, the list shows value for money. Where it does not,
              it shows the highest scores under the price limit.
            </p>
          </div>
          <fieldset>
            <legend className="label">Price limit for score lists</legend>
            <div className="flex gap-1 rounded-md bg-surface-sunk p-1">
              {CAPS.map((c) => (
                <label key={c} className={[
                  "num cursor-pointer rounded px-3 py-1.5 text-sm font-semibold has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-marker",
                  cap === c ? "bg-surface-raised shadow-sm" : "text-ink-soft",
                ].join(" ")}>
                  <input type="radio" name="cap" className="sr-only" checked={cap === c} onChange={() => setCap(c)} />
                  {eur(c)}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        <div className="mt-5 grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
          {ROLES.map((role) => {
            const vfm = d.value_for_money_shown?.[role] ?? false;
            const picks = vfm ? d.value_picks[role] ?? [] : d.budget_picks?.[String(cap)]?.[role] ?? [];
            return (
              <div key={role}>
                <div className="border-b border-rule pb-1">
                  <h3 className="font-semibold">{ROLE_NAMES[role]}s</h3>
                  <p className="text-xs text-ink-faint">
                    {vfm ? "Value for money: score points above what the price predicts" : `Highest score under ${eur(cap)}`}
                  </p>
                </div>
                {picks.length === 0 ? (
                  <p className="mt-2 text-sm text-ink-faint">
                    {vfm || t.leagues_complete === 0 ? "No player meets these rules yet." : `No reliable regular under ${eur(cap)}. Try a higher limit.`}
                  </p>
                ) : <PickList picks={picks} metric={vfm ? "vfm" : "score"} />}
              </div>
            );
          })}
        </div>
      </section>

      <div className="grid gap-10 lg:grid-cols-2">
        <section aria-labelledby="model-title">
          <h2 id="model-title" className="condensed text-2xl font-bold">Scoring model</h2>
          <dl className="mt-3 space-y-3 text-sm">
            <div>
              <dt className="text-ink-soft">Version</dt>
              <dd className="font-semibold">{d.model.version ?? "Not run yet"}</dd>
            </div>
            <div>
              <dt className="text-ink-soft">League-strength adjustment</dt>
              <dd className="font-semibold">
                {adj == null ? "Not calibrated yet" : adj.accepted ? "Active" : "Not active"}
              </dd>
              <dd className="text-ink-soft">
                {adj == null
                  ? "Needs club strength ratings from ClubElo. Until then, scores rank players within their own league only."
                  : adj.reason}
              </dd>
            </div>
          </dl>
        </section>

        <section aria-labelledby="imports-title">
          <h2 id="imports-title" className="condensed text-2xl font-bold">Recent imports</h2>
          {d.imports.length === 0 ? <p className="mt-3 text-sm text-ink-soft">No imports yet.</p> : (
            <table className="mt-3 w-full text-sm">
              <thead>
                <tr className="border-b border-rule text-left text-ink-soft">
                  <th scope="col" className="py-2 pr-3 font-medium">Source</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Finished</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Result</th>
                  <th scope="col" className="py-2 text-right font-medium">Rows</th>
                </tr>
              </thead>
              <tbody>
                {d.imports.map((r, i) => (
                  <tr key={i} className="border-b border-rule/70">
                    <td className="py-2 pr-3">{r.source}<span className="block text-xs text-ink-faint">{r.kind}</span></td>
                    <td className="py-2 pr-3">{timeText(r.finished_at)}</td>
                    <td className={`py-2 pr-3 ${r.status === "failed" ? "text-signal" : ""}`}>
                      {r.status === "success" ? "Succeeded" : r.status === "failed" ? "Failed" : r.status === "partial" ? "Partly done" : "Running"}
                    </td>
                    <td className="num py-2 text-right">{num(r.rows_written)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}
